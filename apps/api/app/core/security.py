"""JWT verification and authenticated user extraction using Supabase Auth."""

import logging
from typing import Annotated

import jwt
from fastapi import Depends, Header, HTTPException, status

from app.core.config import get_settings
from app.schemas.auth import UserProfile

logger = logging.getLogger("researchly")

CREDENTIALS_EXCEPTION = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials.",
    headers={"WWW-Authenticate": "Bearer"},
)


def _extract_token(authorization: str | None) -> str:
    """Parse 'Bearer <token>' header and return the raw token."""
    if not authorization:
        raise CREDENTIALS_EXCEPTION
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise CREDENTIALS_EXCEPTION
    return parts[1]


async def get_current_user(
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> UserProfile:
    """Dependency: validate the Supabase JWT and return the authenticated user.

    Uses the SUPABASE_ANON_KEY as the JWT secret for HS256 verification.
    Supabase JWTs are signed with the project-level JWT secret, which is the
    same value as SUPABASE_ANON_KEY in the Supabase project settings.

    When SUPABASE_ANON_KEY is not configured (Part 0/1 dev mode), returns a
    mock dev user so the health and schema tests still pass.
    """
    settings = get_settings()
    token = _extract_token(authorization)

    # Development bypass: if credentials are not configured, permit a dev token
    if not settings.SUPABASE_ANON_KEY and token == "dev-token":
        return UserProfile(
            id="00000000-0000-0000-0000-000000000000",
            email="dev@researchly.local",
            name="Dev User",
        )

    if not settings.SUPABASE_ANON_KEY:
        logger.warning("SUPABASE_ANON_KEY not set; rejecting all JWT requests.")
        raise CREDENTIALS_EXCEPTION

    try:
        payload = jwt.decode(
            token,
            settings.SUPABASE_ANON_KEY,
            algorithms=["HS256"],
            options={"verify_aud": False},
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session has expired. Please sign in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError as exc:
        logger.debug("JWT validation failed: %s", exc)
        raise CREDENTIALS_EXCEPTION

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


# Convenience type alias for route dependencies
CurrentUser = Annotated[UserProfile, Depends(get_current_user)]
