"""Pydantic schemas for the papers domain."""

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field


class PaperStatus(str, Enum):
    uploaded = "uploaded"
    processing = "processing"
    ready = "ready"
    failed = "failed"


class PaperResponse(BaseModel):
    """Paper row as returned to the frontend."""

    id: UUID
    user_id: UUID
    title: str
    authors: list[str]
    abstract: str | None = None
    publication_year: int | None = None
    file_path: str
    file_size: int | None = None
    total_pages: int | None = None
    status: PaperStatus
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PaperListResponse(BaseModel):
    papers: list[PaperResponse]
    total: int = Field(description="Total number of papers for this user")
