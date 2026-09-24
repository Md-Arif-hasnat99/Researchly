"""Auth API router — profile endpoint and session verification."""

from fastapi import APIRouter

from app.core.security import CurrentUser
from app.core.supabase import get_supabase_client
from app.schemas.auth import UserProfile

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.get("/me", response_model=UserProfile)
async def get_me(current_user: CurrentUser) -> UserProfile:
    """Return the profile of the currently authenticated user.

    Fetches the extended profile row from `public.profiles`.
    Falls back to JWT-derived data if the profile row does not exist yet.
    """
    client = get_supabase_client()

    try:
        result = (
            client.table("profiles")
            .select("id, name, email, avatar_url, created_at, updated_at")
            .eq("id", str(current_user.id))
            .single()
            .execute()
        )
        if result.data:
            return UserProfile.model_validate(result.data)
    except Exception:
        # Profile row may not exist yet (first sign-in before trigger fires);
        # fall through and return JWT-derived data.
        pass

    return current_user


@router.get("/session", response_model=dict)
async def get_session(current_user: CurrentUser) -> dict:
    """Verify session validity and return minimal user info.

    Used by the frontend to validate that a stored token is still active.
    """
    return {
        "authenticated": True,
        "user_id": str(current_user.id),
        "email": current_user.email,
    }
