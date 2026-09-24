"""Papers API router — upload, list, retrieve, delete, ingestion trigger."""

import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException, UploadFile, status

from app.core.logging import logger
from app.core.security import CurrentUser
from app.core.storage import (
    MAX_FILE_SIZE,
    build_storage_path,
    delete_paper_from_storage,
    download_paper,
    upload_paper,
)
from app.core.supabase import get_supabase_client
from app.rag.ingestion.pipeline import run_ingestion
from app.schemas.chunks import ChunkListResponse, ChunkResponse, IngestionStatusResponse
from app.schemas.papers import PaperListResponse, PaperResponse

router = APIRouter(prefix="/papers", tags=["Papers"])

_ALLOWED_CONTENT_TYPES = {"application/pdf"}


def _assert_pdf(file: UploadFile) -> None:
    """Raise 422 if the uploaded file is not a PDF."""
    content_type = (file.content_type or "").split(";")[0].strip().lower()
    if content_type not in _ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Only PDF files are accepted.",
        )


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
    - Enforces a 50 MB size limit.
    - Stores the file in Supabase Storage.
    - Creates a ``papers`` row with status ``uploaded``.
    """
    _assert_pdf(file)

    data = await file.read()
    if len(data) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"File exceeds the {MAX_FILE_SIZE // (1024 * 1024)} MB limit.",
        )

    file_id = str(uuid.uuid4())
    storage_path = build_storage_path(str(current_user.id), file_id)

    # Upload to Supabase Storage
    upload_paper(storage_path, data, file.content_type or "application/pdf")

    # Derive a user-friendly title from the filename (strip extension)
    raw_name = (file.filename or "untitled").rsplit(".", 1)[0].replace("_", " ").replace("-", " ")
    title = raw_name[:255] if raw_name else "Untitled Paper"

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
        logger.error("Download failed for paper %s: %s", paper_id, exc)
        from app.core.supabase import get_supabase_client as _gsc  # local import avoids cycle

        _gsc().table("papers").update(
            {"status": "failed", "error_message": str(exc)[:2000]}
        ).eq("id", paper_id).execute()
        return
    try:
        run_ingestion(paper_id, pdf_bytes)
    except Exception as exc:  # noqa: BLE001
        logger.error("Background ingestion error for %s: %s", paper_id, exc)


# ---------------------------------------------------------------------------
# GET /api/papers
# ---------------------------------------------------------------------------


@router.get("", response_model=PaperListResponse)
async def list_papers(current_user: CurrentUser) -> PaperListResponse:
    """Return all papers belonging to the authenticated user."""
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
async def get_paper(paper_id: str, current_user: CurrentUser) -> PaperResponse:
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
async def delete_paper(paper_id: str, current_user: CurrentUser) -> None:
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
async def list_chunks(paper_id: str, current_user: CurrentUser) -> ChunkListResponse:
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
async def trigger_ingestion(
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

