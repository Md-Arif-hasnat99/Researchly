"""Tests for Part 2: authentication, JWT security, and auth API endpoints."""

from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.security import _extract_token, get_current_user
from app.main import app


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
            mock_settings.return_value = MagicMock(SUPABASE_ANON_KEY="")
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
