"""Tests for Part 2: authentication, JWT security, and auth API endpoints."""

import base64
from unittest.mock import MagicMock, patch

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from httpx import ASGITransport, AsyncClient
from jwt.exceptions import PyJWKClientConnectionError, PyJWKClientError

from app.core.security import _extract_token, get_current_user
from app.main import app


def _es256_keypair():
    return ec.generate_private_key(ec.SECP256R1())


def _ec_public_jwk(public_key, kid: str) -> dict:
    """Render an EC public key as the JWK shape a JWKS endpoint returns."""
    numbers = public_key.public_numbers()

    def b64(value: int, size: int) -> str:
        raw = value.to_bytes(size, "big")
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    return {
        "kty": "EC",
        "crv": "P-256",
        "x": b64(numbers.x, 32),
        "y": b64(numbers.y, 32),
        "kid": kid,
        "alg": "ES256",
        "use": "sig",
    }


def _es256_token(private_key, kid: str, **overrides) -> str:
    payload = {
        "sub": "es256-user-0001",
        "email": "es256@test.local",
        "user_metadata": {"full_name": "Asymmetric User"},
    }
    payload.update(overrides)
    return pyjwt.encode(payload, private_key, algorithm="ES256", headers={"kid": kid})


class TestTokenExtraction:
    def test_extracts_token_from_valid_header(self):
        token = _extract_token("Bearer my-token-abc123")
        assert token == "my-token-abc123"

    def test_raises_on_missing_header(self):
        with pytest.raises(Exception) as exc_info:
            _extract_token(None)
        assert exc_info.value.status_code == 401

    def test_raises_on_wrong_scheme(self):
        with pytest.raises(Exception) as exc_info:
            _extract_token("Basic my-token")
        assert exc_info.value.status_code == 401

    def test_raises_on_malformed_header(self):
        with pytest.raises(Exception) as exc_info:
            _extract_token("onlyone")
        assert exc_info.value.status_code == 401


class TestJWTVerification:
    @pytest.mark.asyncio
    async def test_dev_token_allowed_when_key_unset(self):
        """When SUPABASE_ANON_KEY is empty and dev-token is sent, return dev user."""
        with patch("app.core.security.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(SUPABASE_ANON_KEY="", IS_PRODUCTION=False)
            user = await get_current_user(authorization="Bearer dev-token")
        assert user.email == "dev@researchly.local"
        assert "00000000" in str(user.id)

    @pytest.mark.asyncio
    async def test_rejects_random_token_when_key_configured(self):
        """Random token should fail validation when a key is configured."""
        from fastapi import HTTPException

        with patch("app.core.security.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(SUPABASE_ANON_KEY="a-test-secret-key")
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(authorization="Bearer definitely-not-a-valid-jwt")
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_accepts_valid_hs256_jwt(self):
        """A properly signed JWT with a matching key should be accepted."""
        import jwt as pyjwt

        secret = "test-secret-key-for-unit-test"
        payload = {
            "sub": "user-1234-abcd-5678-efgh",
            "email": "test@researchly.local",
            "user_metadata": {"full_name": "Test Researcher"},
        }
        token = pyjwt.encode(payload, secret, algorithm="HS256")

        with patch("app.core.security.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(SUPABASE_ANON_KEY=secret)
            user = await get_current_user(authorization=f"Bearer {token}")

        assert user.email == "test@researchly.local"
        assert user.name == "Test Researcher"
        assert str(user.id) == "user-1234-abcd-5678-efgh"


class TestAsymmetricJWTVerification:
    """Supabase issues ES256/RS256 tokens for every project created since it
    moved off the shared JWT secret. Verifying those with the anon key as an
    HS256 secret fails for every signed-in user, so they are checked against
    the project JWKS instead."""

    @pytest.mark.asyncio
    async def test_accepts_es256_jwt_verified_against_jwks(self):
        private_key = _es256_keypair()
        jwk = _ec_public_jwk(private_key.public_key(), "kid-es256-1")
        token = _es256_token(private_key, "kid-es256-1")

        client = MagicMock()
        client.get_signing_key_from_jwt.return_value = pyjwt.PyJWK(jwk)

        with patch("app.core.security.get_settings") as mock_settings, patch(
            "app.core.security._jwks_client", return_value=client
        ):
            mock_settings.return_value = MagicMock(
                SUPABASE_ANON_KEY="irrelevant-anon-key",
                SUPABASE_URL="https://project.supabase.co",
            )
            user = await get_current_user(authorization=f"Bearer {token}")

        assert user.email == "es256@test.local"
        assert user.name == "Asymmetric User"
        assert str(user.id) == "es256-user-0001"

    @pytest.mark.asyncio
    async def test_asymmetric_path_looks_up_keys_by_kid(self):
        private_key = _es256_keypair()
        jwk = _ec_public_jwk(private_key.public_key(), "kid-es256-2")
        token = _es256_token(private_key, "kid-es256-2")

        client = MagicMock()
        client.get_signing_key_from_jwt.return_value = pyjwt.PyJWK(jwk)

        with patch("app.core.security.get_settings") as mock_settings, patch(
            "app.core.security._jwks_client", return_value=client
        ) as mock_jwks:
            mock_settings.return_value = MagicMock(
                SUPABASE_ANON_KEY="anon",
                SUPABASE_URL="https://project.supabase.co/",
            )
            await get_current_user(authorization=f"Bearer {token}")

        mock_jwks.assert_called_once_with("https://project.supabase.co/")
        client.get_signing_key_from_jwt.assert_called_once_with(token)

    def test_jwks_client_targets_the_well_known_endpoint(self):
        from app.core.security import _jwks_client

        _jwks_client.cache_clear()
        try:
            assert (
                _jwks_client("https://project.supabase.co/").uri
                == "https://project.supabase.co/auth/v1/.well-known/jwks.json"
            )
            assert (
                _jwks_client("https://project.supabase.co").uri
                == "https://project.supabase.co/auth/v1/.well-known/jwks.json"
            )
        finally:
            _jwks_client.cache_clear()

    @pytest.mark.asyncio
    async def test_rejects_es256_token_signed_by_another_key(self):
        """A token that parses but fails signature verification is 401."""
        from fastapi import HTTPException

        real_key = _es256_keypair()
        attacker_key = _es256_keypair()
        token = _es256_token(attacker_key, "kid-es256-3")

        client = MagicMock()
        client.get_signing_key_from_jwt.return_value = pyjwt.PyJWK(
            _ec_public_jwk(real_key.public_key(), "kid-es256-3")
        )

        with patch("app.core.security.get_settings") as mock_settings, patch(
            "app.core.security._jwks_client", return_value=client
        ):
            mock_settings.return_value = MagicMock(
                SUPABASE_ANON_KEY="anon",
                SUPABASE_URL="https://project.supabase.co",
            )
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(authorization=f"Bearer {token}")

        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_unreachable_jwks_is_503_not_401(self):
        """A key server we cannot reach is our outage, not a bad token:
        answering 401 bounces the user to the login screen."""
        from fastapi import HTTPException

        private_key = _es256_keypair()
        token = _es256_token(private_key, "kid-es256-4")

        client = MagicMock()
        client.get_signing_key_from_jwt.side_effect = PyJWKClientConnectionError(
            "connection refused"
        )

        with patch("app.core.security.get_settings") as mock_settings, patch(
            "app.core.security._jwks_client", return_value=client
        ):
            mock_settings.return_value = MagicMock(
                SUPABASE_ANON_KEY="anon",
                SUPABASE_URL="https://project.supabase.co",
            )
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(authorization=f"Bearer {token}")

        assert exc_info.value.status_code == 503

    @pytest.mark.asyncio
    async def test_unknown_kid_is_401(self):
        from fastapi import HTTPException

        private_key = _es256_keypair()
        token = _es256_token(private_key, "kid-not-published")

        client = MagicMock()
        client.get_signing_key_from_jwt.side_effect = PyJWKClientError(
            "Unable to find a signing key that matches: kid-not-published"
        )

        with patch("app.core.security.get_settings") as mock_settings, patch(
            "app.core.security._jwks_client", return_value=client
        ):
            mock_settings.return_value = MagicMock(
                SUPABASE_ANON_KEY="anon",
                SUPABASE_URL="https://project.supabase.co",
            )
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(authorization=f"Bearer {token}")

        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_expired_es256_token_reports_expiry(self):
        from fastapi import HTTPException

        private_key = _es256_keypair()
        jwk = _ec_public_jwk(private_key.public_key(), "kid-es256-5")
        token = _es256_token(private_key, "kid-es256-5", exp=1_700_000_000)

        client = MagicMock()
        client.get_signing_key_from_jwt.return_value = pyjwt.PyJWK(jwk)

        with patch("app.core.security.get_settings") as mock_settings, patch(
            "app.core.security._jwks_client", return_value=client
        ):
            mock_settings.return_value = MagicMock(
                SUPABASE_ANON_KEY="anon",
                SUPABASE_URL="https://project.supabase.co",
            )
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(authorization=f"Bearer {token}")

        assert exc_info.value.status_code == 401
        assert "expired" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_asymmetric_token_without_supabase_url_is_503(self):
        from fastapi import HTTPException

        private_key = _es256_keypair()
        token = _es256_token(private_key, "kid-es256-6")

        with patch("app.core.security.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                SUPABASE_ANON_KEY="anon", SUPABASE_URL=""
            )
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(authorization=f"Bearer {token}")

        assert exc_info.value.status_code == 503

    @pytest.mark.asyncio
    async def test_algorithm_is_taken_from_jwks_not_token_header(self):
        """The token header picks which verifier runs, but never how the
        signature is checked — otherwise a caller could downgrade the check."""
        private_key = _es256_keypair()
        jwk = _ec_public_jwk(private_key.public_key(), "kid-es256-7")
        token = _es256_token(private_key, "kid-es256-7")

        client = MagicMock()
        signing_key = pyjwt.PyJWK(jwk)
        client.get_signing_key_from_jwt.return_value = signing_key

        with patch("app.core.security.get_settings") as mock_settings, patch(
            "app.core.security._jwks_client", return_value=client
        ), patch("jwt.decode", wraps=pyjwt.decode) as spy:
            mock_settings.return_value = MagicMock(
                SUPABASE_ANON_KEY="anon",
                SUPABASE_URL="https://project.supabase.co",
            )
            await get_current_user(authorization=f"Bearer {token}")

        algorithms = spy.call_args.kwargs["algorithms"]
        assert algorithms == [signing_key.algorithm_name]
        assert "HS256" not in algorithms

    @pytest.mark.asyncio
    async def test_hs256_token_does_not_reach_the_jwks(self):
        """Legacy shared-secret projects keep the original code path."""
        secret = "legacy-shared-secret"
        token = pyjwt.encode(
            {"sub": "legacy-1", "email": "legacy@test.local"},
            secret,
            algorithm="HS256",
        )

        with patch("app.core.security.get_settings") as mock_settings, patch(
            "app.core.security._jwks_client"
        ) as mock_jwks:
            mock_settings.return_value = MagicMock(
                SUPABASE_ANON_KEY=secret,
                SUPABASE_URL="https://project.supabase.co",
            )
            user = await get_current_user(authorization=f"Bearer {token}")

        assert user.email == "legacy@test.local"
        mock_jwks.assert_not_called()


class TestAuthEndpoints:
    @pytest.mark.asyncio
    async def test_me_endpoint_requires_auth(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/auth/me")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_session_endpoint_requires_auth(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/auth/session")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_me_returns_profile_with_valid_jwt(self):
        import jwt as pyjwt

        secret = "test-secret-for-endpoint"
        token = pyjwt.encode(
            {
                "sub": "test-user-id-00000001",
                "email": "endpoint@test.local",
                "user_metadata": {},
            },
            secret,
            algorithm="HS256",
        )

        with patch("app.core.security.get_settings") as mock_settings, \
             patch("app.api.auth.get_supabase_client") as mock_client:

            mock_settings.return_value = MagicMock(SUPABASE_ANON_KEY=secret)
            # Simulate profile not found (new user); falls back to JWT data
            mock_table = MagicMock()
            execute_mock = (
                mock_table.select.return_value.eq.return_value.single.return_value.execute
            )
            execute_mock.side_effect = Exception("No rows")
            mock_client.return_value.table.return_value = mock_table

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get(
                    "/api/auth/me", headers={"Authorization": f"Bearer {token}"}
                )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "test-user-id-00000001"
        assert data["email"] == "endpoint@test.local"
