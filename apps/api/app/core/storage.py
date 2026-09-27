"""Supabase Storage helpers for paper PDF management."""

import logging
from pathlib import PurePosixPath

from app.core.config import get_settings
from app.core.supabase import get_supabase_client

logger = logging.getLogger("researchly")

#: The one source of truth for the bucket name. The storage migration
#: provisions policies for exactly this string; a test asserts the two
#: agree, because a mismatch leaves every policy inert and the bucket
#: unprotected while the code looks correct.
BUCKET = "papers"


def max_file_size() -> int:
    """Upload ceiling in bytes, from configuration."""
    return get_settings().MAX_UPLOAD_MB * 1024 * 1024


#: Kept for the callers and tests that imported it as a constant. The
#: default matches MAX_UPLOAD_MB; request handling calls max_file_size()
#: so a deployment can lower or raise the limit without a code change.
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB


def build_storage_path(user_id: str, file_id: str) -> str:
    """Return the deterministic storage path for a paper PDF.

    Format: ``{user_id}/{file_id}.pdf``

    Both halves are server-generated — a JWT subject and a fresh UUID —
    so a caller-supplied filename can never reach this path. The
    ``{user_id}/`` prefix is what the storage RLS policies key on, which
    is why the layout is part of the security model rather than a
    naming preference.
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


def download_paper(storage_path: str) -> bytes:
    """Download a paper PDF from Supabase Storage and return its bytes.

    Args:
        storage_path: Path within the ``papers`` bucket.

    Returns:
        Raw PDF bytes.

    Raises:
        RuntimeError: If the download fails.
    """
    client = get_supabase_client()
    try:
        data: bytes = client.storage.from_(BUCKET).download(storage_path)
        logger.info("Downloaded paper from storage: %s (%d bytes)", storage_path, len(data))
        return data
    except Exception as exc:
        # Deliberately no path and no underlying message: this text is
        # persisted on the paper row and returned to the user by
        # GET /api/papers/{id}, so it must not disclose the storage
        # layout or a driver's error verbatim. The full error is in the
        # log, where the request id ties it to this call.
        raise RuntimeError("Failed to download the paper from storage.") from exc

