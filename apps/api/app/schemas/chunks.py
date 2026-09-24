"""Pydantic schemas for the paper_chunks domain."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class ChunkResponse(BaseModel):
    """A single text chunk as returned to the frontend."""

    id: UUID
    paper_id: UUID
    content: str
    page_number: int
    section: str | None = None
    chunk_index: int
    created_at: datetime

    model_config = {"from_attributes": True}


class ChunkListResponse(BaseModel):
    chunks: list[ChunkResponse]
    total: int


class IngestionStatusResponse(BaseModel):
    """Returned immediately after triggering ingestion."""

    paper_id: str
    status: str
    message: str
