"""Papers API router — upload, list, retrieve, delete."""

import uuid

from fastapi import APIRouter, HTTPException, UploadFile, status

from app.core.logging import logger
from app.core.security import CurrentUser
from app.core.storage import (
    MAX_FILE_SIZE,
    build_storage_path,
    delete_paper_from_storage,
    upload_paper,
)
from app.core.supabase import get_supabase_client
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
    return PaperResponse(**result.data[0])


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
