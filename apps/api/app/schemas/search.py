"""Pydantic schema for search requests and results."""

from uuid import UUID

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    paper_ids: list[UUID] | None = Field(
        default=None,
        description="Restrict search to specific paper IDs. None = all user papers.",
    )
    top_k: int = Field(default=8, ge=1, le=20)
    similarity_threshold: float = Field(default=0.65, ge=0.0, le=1.0)


class SearchResultChunk(BaseModel):
    chunk_id: UUID
    paper_id: UUID
    paper_title: str
    page_number: int
    section: str | None = None
    content: str
    similarity_score: float


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResultChunk]
    total_results: int
