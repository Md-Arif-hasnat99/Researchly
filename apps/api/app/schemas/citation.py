"""Pydantic schema for Citation objects."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class CitationResponse(BaseModel):
    id: UUID
    message_id: UUID
    paper_id: UUID
    chunk_id: UUID
    page_number: int
    similarity_score: float | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
