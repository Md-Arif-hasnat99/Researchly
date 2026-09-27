"""Papers API router — upload, list, retrieve, delete, ingestion trigger."""

import re
import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException, UploadFile, status

from app.core.errors import safe_error_message
from app.core.logging import logger
from app.core.security import CurrentUser
from app.core.storage import (
    build_storage_path,
    delete_paper_from_storage,
    download_paper,
    max_file_size,
    upload_paper,
)
from app.core.supabase import get_supabase_client
from app.rag.ingestion.pipeline import run_ingestion
from app.schemas.chunks import ChunkListResponse, ChunkResponse, IngestionStatusResponse
from app.schemas.papers import PaperListResponse, PaperResponse

router = APIRouter(prefix="/papers", tags=["Papers"])

_ALLOWED_CONTENT_TYPES = {"application/pdf"}

#: Every PDF starts with these five bytes. Checked because the declared
#: Content-Type is attacker-controlled: without this, a 2 GB archive with
#: `Content-Type: application/pdf` is stored in full and only discovered
#: to be unparseable later, in the background task, after the bytes are
#: already in the bucket.
_PDF_MAGIC = b"%PDF-"

_READ_CHUNK = 1024 * 1024  # 1 MiB

#: Characters stripped from a client-supplied filename. C0/C1 controls
#: can corrupt logs and terminal output, and zero-width characters
#: render as nothing while still being stored, so two visually identical
#: titles can differ in the database.
_UNSAFE_FILENAME_CHARS = re.compile(r"[\x00-\x1f\x7f-\x9f-‏‪-‮﻿]")


def _assert_pdf(file: UploadFile) -> None:
    """Raise 422 if the uploaded file is not declared as a PDF."""
    content_type = (file.content_type or "").split(";")[0].strip().lower()
    if content_type not in _ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Only PDF files are accepted.",
        )


async def _read_capped(file: UploadFile, limit: int) -> bytes:
    """Read at most *limit* bytes, stopping as soon as the cap is passed.

    Reading the whole body first and checking its length afterwards means
    a client can make the server buffer an arbitrarily large upload
    before being refused — an unauthenticated-ish memory amplifier, and
    the request is not even rate limited by size. This stops at the first
    byte past the limit instead.
    """
    data = await file.read(_READ_CHUNK)
    while len(data) <= limit:
        chunk = await file.read(_READ_CHUNK)
        if not chunk:
            break
        data += chunk
    if len(data) > limit:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"File exceeds the {limit // (1024 * 1024)} MB limit.",
        )
    return data


def _assert_is_pdf_bytes(data: bytes) -> None:
    """Raise 422 unless the content really is a PDF, not just declared as one."""
    if not data.startswith(_PDF_MAGIC):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="The uploaded file is not a valid PDF.",
        )


def sanitize_title_from_filename(filename: str | None) -> str:
    """Turn an uploaded filename into a presentable paper title.

    The filename is user input that ends up in the database and in the
    library view, so it is reduced to something safe and legible rather
    than trusted: any directory component is dropped, control and
    zero-width characters are removed, whitespace is collapsed, and the
    result is length-capped. A name that sanitizes away to nothing
    becomes a placeholder instead of an empty row.
    """
    raw = (filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    raw = _UNSAFE_FILENAME_CHARS.sub("", raw)
    stem = raw.rsplit(".", 1)[0] if "." in raw else raw
    # A name that is only dots and separators ("....pdf") leaves nothing
    # usable behind; lstrip keeps a leading dot from becoming the title.
    stem = stem.strip(" .")
    cleaned = " ".join(stem.replace("_", " ").replace("-", " ").split())
    return cleaned[:255] or "Untitled Paper"


# ---------------------------------------------------------------------------
# POST /api/papers
# ---------------------------------------------------------------------------


@router.post("", response_model=PaperResponse, status_code=status.HTTP_201_CREATED)
async def upload_paper_endpoint(
    file: UploadFile,
    current_user: CurrentUser,
    background_tasks: BackgroundTasks,
) -> PaperResponse:
    """Upload a PDF research paper.

    - Validates MIME type (must be ``application/pdf``).
    - Enforces the configured size limit, aborting the read as soon as
      the file exceeds it.
    - Confirms the bytes really are a PDF, not just declared as one.
    - Stores the file in Supabase Storage.
    - Creates a ``papers`` row with status ``uploaded``.
    """
    _assert_pdf(file)

    data = await _read_capped(file, max_file_size())
    _assert_is_pdf_bytes(data)

    file_id = str(uuid.uuid4())
    storage_path = build_storage_path(str(current_user.id), file_id)

    # Upload to Supabase Storage
    upload_paper(storage_path, data, file.content_type or "application/pdf")

    # Derive a user-friendly title from the filename (strip extension)
    title = sanitize_title_from_filename(file.filename)

    client = get_supabase_client()
    result = (
        client.table("papers")
        .insert(
            {
                "user_id": str(current_user.id),
                "title": title,
                "authors": [],
                "file_path": storage_path,
                "file_size": len(data),
                "status": "uploaded",
            }
        )
        .execute()
    )

    if not result.data:
        # Storage upload succeeded but DB insert failed; attempt cleanup.
        delete_paper_from_storage(storage_path)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create paper record.",
        )

    logger.info("Paper created: %s for user %s", file_id, current_user.id)

    paper_id = result.data[0]["id"]

    # Kick off ingestion in the background so the API returns immediately
    background_tasks.add_task(_ingest_paper, paper_id, storage_path)

    return PaperResponse(**result.data[0])


def _ingest_paper(paper_id: str, file_path: str) -> None:
    """Background task: download the PDF then run the ingestion pipeline."""
    try:
        pdf_bytes = download_paper(file_path)
    except Exception as exc:  # noqa: BLE001
        logger.error("Download failed for paper %s: %s", paper_id, exc, exc_info=True)
        from app.core.supabase import get_supabase_client as _gsc  # local import avoids cycle

        # Scrubbed before it is stored: error_message is returned by the
        # paper endpoints, so whatever lands here is user-visible.
        _gsc().table("papers").update(
            {
                "status": "failed",
                "error_message": safe_error_message(
                    exc, fallback="Could not read the uploaded file."
                ),
            }
        ).eq("id", paper_id).execute()
        return
    try:
        run_ingestion(paper_id, pdf_bytes)
    except Exception as exc:  # noqa: BLE001
        logger.error("Background ingestion error for %s: %s", paper_id, exc, exc_info=True)


# ---------------------------------------------------------------------------
# GET /api/papers
# ---------------------------------------------------------------------------


@router.get("", response_model=PaperListResponse)
def list_papers(current_user: CurrentUser) -> PaperListResponse:
    """Return all papers belonging to the authenticated user.

    Sync ``def`` on purpose (as with the other read routes): the
    Supabase call is blocking, and an ``async def`` handler would run
    it on the event loop and stall every concurrent request. FastAPI
    threadpools sync handlers.
    """
    client = get_supabase_client()
    result = (
        client.table("papers")
        .select("*")
        .eq("user_id", str(current_user.id))
        .order("created_at", desc=True)
        .execute()
    )
    papers = [PaperResponse(**row) for row in (result.data or [])]
    return PaperListResponse(papers=papers, total=len(papers))


# ---------------------------------------------------------------------------
# GET /api/papers/{paper_id}
# ---------------------------------------------------------------------------


@router.get("/{paper_id}", response_model=PaperResponse)
def get_paper(paper_id: str, current_user: CurrentUser) -> PaperResponse:
    """Return a single paper by ID (ownership enforced)."""
    client = get_supabase_client()
    try:
        result = (
            client.table("papers")
            .select("*")
            .eq("id", paper_id)
            .eq("user_id", str(current_user.id))
            .single()
            .execute()
        )
    except Exception:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Paper not found.")

    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Paper not found.")

    return PaperResponse(**result.data)


# ---------------------------------------------------------------------------
# DELETE /api/papers/{paper_id}
# ---------------------------------------------------------------------------


@router.delete("/{paper_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_paper(paper_id: str, current_user: CurrentUser) -> None:
    """Delete a paper and its storage object (ownership enforced)."""
    client = get_supabase_client()

    # Fetch first to verify ownership and get the storage path
    try:
        result = (
            client.table("papers")
            .select("id, file_path")
            .eq("id", paper_id)
            .eq("user_id", str(current_user.id))
            .single()
            .execute()
        )
    except Exception:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Paper not found.")

    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Paper not found.")

    file_path: str = result.data["file_path"]

    # Delete DB row (cascades to paper_chunks and citations via FK)
    client.table("papers").delete().eq("id", paper_id).execute()

    # Delete storage object (best-effort)
    delete_paper_from_storage(file_path)

    logger.info("Paper deleted: %s by user %s", paper_id, current_user.id)


# ---------------------------------------------------------------------------
# GET /api/papers/{paper_id}/chunks
# ---------------------------------------------------------------------------


@router.get("/{paper_id}/chunks", response_model=ChunkListResponse)
def list_chunks(paper_id: str, current_user: CurrentUser) -> ChunkListResponse:
    """Return all text chunks for a paper (ownership enforced)."""
    client = get_supabase_client()

    # Verify ownership
    try:
        owner_check = (
            client.table("papers")
            .select("id")
            .eq("id", paper_id)
            .eq("user_id", str(current_user.id))
            .single()
            .execute()
        )
    except Exception:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Paper not found.")

    if not owner_check.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Paper not found.")

    result = (
        client.table("paper_chunks")
        .select("id, paper_id, content, page_number, section, chunk_index, created_at")
        .eq("paper_id", paper_id)
        .order("chunk_index")
        .execute()
    )
    chunks = [ChunkResponse(**row) for row in (result.data or [])]
    return ChunkListResponse(chunks=chunks, total=len(chunks))


# ---------------------------------------------------------------------------
# POST /api/papers/{paper_id}/ingest  (manual re-trigger)
# ---------------------------------------------------------------------------


@router.post("/{paper_id}/ingest", response_model=IngestionStatusResponse)
def trigger_ingestion(
    paper_id: str,
    current_user: CurrentUser,
    background_tasks: BackgroundTasks,
) -> IngestionStatusResponse:
    """Manually trigger (or re-trigger) the ingestion pipeline for a paper.

    Useful when a paper is stuck in ``uploaded`` or ``failed`` state.
    """
    client = get_supabase_client()

    # Verify ownership and get the file_path
    try:
        result = (
            client.table("papers")
            .select("id, file_path, status")
            .eq("id", paper_id)
            .eq("user_id", str(current_user.id))
            .single()
            .execute()
        )
    except Exception:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Paper not found.")

    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Paper not found.")

    file_path: str = result.data["file_path"]
    current_status: str = result.data["status"]

    # Atomically claim the paper by flipping its status from a non-processing
    # state to "processing". If the update affects 0 rows the paper is already
    # being processed and we return 409 to avoid duplicate runs.
    if current_status == "processing":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ingestion is already in progress for this paper.",
        )

    client.table("papers").update({"status": "processing"}).eq(
        "id", paper_id
    ).neq("status", "processing").execute()

    # Pass only the file_path; the background helper downloads the PDF itself
    # so this async endpoint is never blocked by synchronous I/O.
    background_tasks.add_task(_ingest_paper, paper_id, file_path)

    return IngestionStatusResponse(
        paper_id=paper_id,
        status="processing",
        message="Ingestion pipeline started.",
    )

