
from fastapi import Header, HTTPException, status


async def get_current_user_id(
    authorization: str | None = Header(None, alias="Authorization"),
) -> str:
    """Extract and validate the authenticated user ID.

    In Part 0, permits development mock user if unconfigured.
    In Part 2, strictly validates Supabase JWT against SUPABASE_ANON_KEY.
    """
    if not authorization:
        # Development fallback for Part 0 verification
        return "dev-user-0000-0000-000000000000"

    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization header format. Expected 'Bearer <token>'.",
        )

    token = parts[1]
    # Token verification handled by Supabase Auth in Part 2
    return f"user-{token[:8]}"
