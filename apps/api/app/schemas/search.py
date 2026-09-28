"""Pydantic schema for search requests and results."""

from enum import Enum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class SearchMode(str, Enum):
    """Which retrievers to run for a query (FR-14).

    ``hybrid`` is the default: it fuses vector and keyword results.
    ``vector`` is the pre-FR-14 semantic-only behaviour, kept because it
    is the right tool for conceptual questions where the wording of the
    query matters more than its literal terms.  ``keyword`` is the
    lexical retriever on its own, which is what exact-name lookups want
    and which needs no embedding call at all.
    """

    vector = "vector"
    keyword = "keyword"
    hybrid = "hybrid"


# Which retriever(s) surfaced a given chunk.  Reported per result so a
# hit can be explained: a chunk found by keyword alone is an exact-term
# match, and one found by both is the strongest evidence of relevance.
MatchSource = Literal["vector", "keyword"]


class SearchResultChunk(BaseModel):
    chunk_id: UUID
    paper_id: UUID
    paper_title: str
    page_number: int
    section: str | None = None
    content: str
    similarity_score: float | None = Field(
        default=None,
        description=(
            "Cosine similarity. None when the chunk was found only by "
            "keyword search, which never computes an embedding."
        ),
    )
    matched_by: list[MatchSource] = Field(
        default_factory=list,
        description="Retrievers that surfaced this chunk, in fusion order.",
    )
    fusion_score: float | None = Field(
        default=None,
        description=(
            "Reciprocal-rank-fusion score. Only set in hybrid mode; it "
            "measures ranked agreement between retrievers, not semantic "
            "similarity, and is not comparable to similarity_score."
        ),
    )
