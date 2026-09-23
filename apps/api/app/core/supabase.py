from functools import lru_cache

from supabase import Client, create_client

from app.core.config import get_settings
from app.core.logging import logger


@lru_cache
def get_supabase_client() -> Client:
    """Return a cached Supabase client using the service role key.

    The service role key bypasses RLS and is used server-side only.
    Never expose this key to the browser.
    """
    settings = get_settings()

    if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_ROLE_KEY:
        logger.warning(
            "Supabase credentials are not configured. "
            "Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in your .env file."
        )

    client = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
    logger.info("Supabase service-role client initialized.")
    return client


def get_supabase_anon_client() -> Client:
    """Return a Supabase client using the anon key (respects RLS).

    Use this for operations that should be scoped to the authenticated user.
    """
    settings = get_settings()
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_ANON_KEY)
