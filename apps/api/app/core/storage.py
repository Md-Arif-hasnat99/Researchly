"""Supabase Storage helpers for paper PDF management."""

import logging
from pathlib import PurePosixPath

from app.core.supabase import get_supabase_client

logger = logging.getLogger("researchly")

BUCKET = "papers"
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB


def build_storage_path(user_id: str, file_id: str) -> str:
    """Return the deterministic storage path for a paper PDF.

    Format: ``{user_id}/{file_id}.pdf``
    """
    return str(PurePosixPath(user_id) / f"{file_id}.pdf")


def upload_paper(storage_path: str, data: bytes, content_type: str = "application/pdf") -> str:
    """Upload PDF bytes to Supabase Storage.

    Returns the storage path on success, raises on failure.
    """
    client = get_supabase_client()
    client.storage.from_(BUCKET).upload(
        path=storage_path,
        file=data,
        file_options={"content-type": content_type, "upsert": "false"},
    )
    logger.info("Uploaded paper to storage: %s", storage_path)
    return storage_path


def delete_paper_from_storage(storage_path: str) -> None:
    """Remove a paper PDF from Supabase Storage.

    Logs a warning instead of raising if the object is already gone.
    """
    client = get_supabase_client()
    try:
        client.storage.from_(BUCKET).remove([storage_path])
        logger.info("Deleted paper from storage: %s", storage_path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not delete storage object %s: %s", storage_path, exc)
