"""Pydantic schema for search requests and results."""

from enum import Enum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


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


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    paper_ids: list[UUID] | None = Field(
        default=None,
        description="Restrict search to specific paper IDs. None = all user papers.",
    )
    top_k: int = Field(default=8, ge=1, le=20)
    similarity_threshold: float = Field(default=0.65, ge=0.0, le=1.0)
    mode: SearchMode = Field(
        default=SearchMode.hybrid,
        description="Retrieval strategy. hybrid = vector + keyword fused by rank.",
    )
    rerank: bool | None = Field(
        default=None,
        description=(
            "Rerank the candidate set with a relevance model before "
            "truncating (FR-15). None = server default."
        ),
    )

    @field_validator("query")
    @classmethod
    def _reject_blank_query(cls, value: str) -> str:
        """Reject whitespace-only queries.

        ``min_length=1`` admits " ", which is useless to both retrievers:
        it embeds to noise and produces an empty tsquery.  Rejecting it
        here keeps the failure a 422 instead of an empty 200 that reads
        like "nothing in your library matches".
        """
        if not value.strip():
            raise ValueError("query must not be blank")
        return value


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


class SearchResponse(BaseModel):
    query: str
    mode: SearchMode = Field(
        description=(
            "The retriever that actually produced these results. Differs "
            "from the requested mode when hybrid search had to fall back "
            "to vector-only because keyword search was unavailable."
        ),
    )
    results: list[SearchResultChunk]
    total_results: int
    reranked: bool = Field(
        default=False,
        description=(
            "True only when a reranker actually reordered the results. "
            "False covers both 'not requested' and 'requested but did not "
            "apply', so a caller never implies model involvement that did "
            "not happen."
        ),
    )
