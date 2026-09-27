"""JWT verification and authenticated user extraction using Supabase Auth."""

import asyncio
import logging
from functools import lru_cache
from typing import Annotated, Any

import jwt
from fastapi import Depends, Header, HTTPException, status
from jwt import PyJWKClient
from jwt.exceptions import PyJWKClientConnectionError, PyJWKClientError

from app.core.config import get_settings
from app.schemas.auth import UserProfile

logger = logging.getLogger("researchly")

CREDENTIALS_EXCEPTION = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials.",
    headers={"WWW-Authenticate": "Bearer"},
)

EXPIRED_EXCEPTION = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Session has expired. Please sign in again.",
    headers={"WWW-Authenticate": "Bearer"},
)

# A token we cannot verify because the signing keys are out of reach is not
# the caller's fault, so it must not be reported as 401: answering 401 sends
# the user back to the login screen and hides a server-side outage.
VERIFICATION_UNAVAILABLE_EXCEPTION = HTTPException(
    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
    detail="Could not verify session right now. Please try again.",
)

# Where Supabase publishes the public halves of its signing keys.
JWKS_PATH = "/auth/v1/.well-known/jwks.json"

# Supabase issues sessions under its own asymmetric keys (ES256 by default)
# for every project created since it moved off the shared JWT secret. These
# must be verified against the project JWKS, never against SUPABASE_ANON_KEY.
ASYMMETRIC_ALGORITHMS = frozenset(
    {
        "RS256",
        "RS384",
        "RS512",
        "PS256",
        "PS384",
        "PS512",
        "ES256",
        "ES256K",
        "ES384",
        "ES512",
        "EdDSA",
    }
)


def _extract_token(authorization: str | None) -> str:
    """Parse 'Bearer <token>' header and return the raw token."""
    if not authorization:
        raise CREDENTIALS_EXCEPTION
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise CREDENTIALS_EXCEPTION
    return parts[1]


def _token_algorithm(token: str) -> str | None:
    """Read the unverified `alg` header, or None if the token is not a JWT."""
    try:
        return jwt.get_unverified_header(token).get("alg")
    except jwt.PyJWTError:
        return None


@lru_cache(maxsize=4)
def _jwks_client(supabase_url: str) -> PyJWKClient:
    """Cached JWKS fetcher. Key sets are re-read every 5 minutes, which is
    what makes a Supabase key rotation survive without a redeploy."""
    return PyJWKClient(
        f"{supabase_url.rstrip('/')}{JWKS_PATH}",
        cache_keys=True,
        lifespan=300,
        timeout=5,
    )


def _verify_asymmetric(token: str, supabase_url: str) -> dict[str, Any]:
    """Verify a token signed with Supabase's own asymmetric keys.

    The algorithm comes from the JWKS entry that matched the token's `kid`,
    never from the token's own header: trusting the header would let a
    caller pick the algorithm the signature is checked with.
    """
    signing_key = _jwks_client(supabase_url).get_signing_key_from_jwt(token)
    return jwt.decode(
        token,
        signing_key.key,
        algorithms=[signing_key.algorithm_name],
        options={"verify_aud": False},
    )


async def get_current_user(
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> UserProfile:
    """Dependency: validate the Supabase JWT and return the authenticated user.

    Supabase has two token flavours and both are in the field:

    * Legacy projects sign with HS256, using the project JWT secret — which
      is the value of SUPABASE_ANON_KEY.
    * Every project created since Supabase moved to its own signing keys
      issues ES256/RS256 tokens that SUPABASE_ANON_KEY cannot verify at all,
      because the anon key is not a shared secret with the auth server. Those
      are verified against the project JWKS instead.

    The algorithm is read from the token header purely to choose between the
    two, never to decide how a signature is checked.

    When SUPABASE_ANON_KEY is not configured (Part 0/1 dev mode), returns a
    mock dev user so the health and schema tests still pass.
    """
    settings = get_settings()
    token = _extract_token(authorization)

    # Development bypass: when no credentials are configured, permit a
    # dev token so the app is usable before Supabase is wired up. Gated on
    # ENVIRONMENT as well as on the missing key, because a production
    # deployment that ships with an empty SUPABASE_ANON_KEY would
    # otherwise hand a fixed identity to anyone sending `dev-token` —
    # and a missing key is exactly the mistake that reaches production.
    if not settings.SUPABASE_ANON_KEY and token == "dev-token":
        if settings.IS_PRODUCTION:
            logger.error(
                "Refusing the dev-token auth bypass: ENVIRONMENT is production. "
                "Set SUPABASE_ANON_KEY."
            )
            raise CREDENTIALS_EXCEPTION
        return UserProfile(
            id="00000000-0000-0000-0000-000000000000",
            email="dev@researchly.local",
            name="Dev User",
        )

    if not settings.SUPABASE_ANON_KEY:
        logger.warning("SUPABASE_ANON_KEY not set; rejecting all JWT requests.")
        raise CREDENTIALS_EXCEPTION

    if _token_algorithm(token) in ASYMMETRIC_ALGORITHMS:
        payload = await _verify_with_jwks(token, settings.SUPABASE_URL)
    else:
        payload = _verify_with_shared_secret(token, settings.SUPABASE_ANON_KEY)

    user_id: str | None = payload.get("sub")
    if not user_id:
        raise CREDENTIALS_EXCEPTION

    email: str | None = payload.get("email")
    user_metadata: dict = payload.get("user_metadata", {})

    return UserProfile(
        id=user_id,
        email=email,
        name=user_metadata.get("full_name") or user_metadata.get("name"),
        avatar_url=user_metadata.get("avatar_url"),
    )


async def _verify_with_jwks(token: str, supabase_url: str) -> dict[str, Any]:
    """Verify against Supabase's JWKS, off the event loop."""
    if not supabase_url:
        logger.error(
            "Received an asymmetric session token but SUPABASE_URL is not set; "
            "the project's signing keys cannot be located."
        )
        raise VERIFICATION_UNAVAILABLE_EXCEPTION

    try:
        return await asyncio.to_thread(_verify_asymmetric, token, supabase_url)
    except jwt.ExpiredSignatureError:
        raise EXPIRED_EXCEPTION
    except PyJWKClientConnectionError as exc:
        # Reported before the InvalidTokenError branch below, because
        # PyJWKClientError subclasses it: an unreachable key server would
        # otherwise be reported to the user as bad credentials.
        logger.error("Could not reach the Supabase JWKS endpoint: %s", exc)
        raise VERIFICATION_UNAVAILABLE_EXCEPTION
    except (PyJWKClientError, jwt.InvalidTokenError) as exc:
        logger.debug("JWKS validation failed: %s", exc)
        raise CREDENTIALS_EXCEPTION


def _verify_with_shared_secret(token: str, secret: str) -> dict[str, Any]:
    """Verify a legacy HS256 token against the shared project secret."""
    try:
        return jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            options={"verify_aud": False},
        )
    except jwt.ExpiredSignatureError:
        raise EXPIRED_EXCEPTION
    except jwt.InvalidTokenError as exc:
        logger.debug("JWT validation failed: %s", exc)
        raise CREDENTIALS_EXCEPTION


# Convenience type alias for route dependencies
CurrentUser = Annotated[UserProfile, Depends(get_current_user)]
