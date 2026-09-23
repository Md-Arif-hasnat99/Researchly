"""Pydantic schemas for Paper domain objects."""

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field


class PaperStatus(str, Enum):
    uploaded = "uploaded"
    processing = "processing"
    ready = "ready"
    failed = "failed"


class PaperBase(BaseModel):
    title: str = Field(default="Untitled Paper", max_length=500)
    authors: list[str] = Field(default_factory=list)
    abstract: str | None = None
    publication_year: int | None = Field(default=None, ge=1000, le=2100)


class PaperCreate(PaperBase):
    file_path: str
    file_size: int | None = None


class PaperUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=500)
    authors: list[str] | None = None
    abstract: str | None = None
    publication_year: int | None = Field(default=None, ge=1000, le=2100)
    status: PaperStatus | None = None
    error_message: str | None = None
    total_pages: int | None = None


class PaperResponse(PaperBase):
    id: UUID
    user_id: UUID
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
    total: int
