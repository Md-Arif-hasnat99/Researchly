from functools import lru_cache

from supabase import Client, create_client

from app.core.config import get_settings
from app.core.logging import logger


_supabase_service_client: Client | None = None
_supabase_anon_client: Client | None = None


@lru_cache
def get_supabase_client() -> Client:
    """Return a cached Supabase client using the service role key.

    The service role key bypasses RLS and is used server-side only.
    Never expose this key to the browser.
    """
    global _supabase_service_client
    if _supabase_service_client is None:
        settings = get_settings()

        if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_ROLE_KEY:
            logger.warning(
                "Supabase credentials are not configured. "
                "Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in your .env file."
            )

        _supabase_service_client = create_client(
            settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY
        )
        logger.info("Supabase service-role client initialized.")
    return _supabase_service_client


def get_supabase_anon_client() -> Client:
    """Return a Supabase client using the anon key (respects RLS).

    Use this for operations that should be scoped to the authenticated user.
    """
    global _supabase_anon_client
    if _supabase_anon_client is None:
        settings = get_settings()
        _supabase_anon_client = create_client(
            settings.SUPABASE_URL, settings.SUPABASE_ANON_KEY
        )
        logger.info("Supabase anon client initialized.")
    return _supabase_anon_client
