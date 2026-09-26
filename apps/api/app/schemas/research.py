"""Pydantic schemas for multi-paper research endpoints (FR-10 through FR-13)."""

from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field

# Default comparison aspects (FR-11). Each becomes one row of the matrix.
DEFAULT_ASPECTS: list[str] = [
    "Dataset",
    "Model",
    "Method",
    "Metrics",
    "Results",
    "Limitations",
]


class CompareRequest(BaseModel):
    """Request body for POST /api/research/compare."""

    paper_ids: list[UUID] = Field(
        ...,
        min_length=2,
        max_length=6,
        description="Two to six papers to compare. All must belong to the caller.",
    )
    aspects: list[str] | None = Field(
        default=None,
        description=(
            "Comparison aspects (rows of the matrix). "
            "Omit to use the default set from FR-11."
        ),
    )
    per_paper_top_k: int = Field(
        default=6,
        ge=1,
        le=20,
        description="Max context chunks retrieved per paper.",
    )
    focus: str | None = Field(
        default=None,
        max_length=1000,
        description="Optional user focus, e.g. 'compare evaluation methodology'.",
    )


class CompareCell(BaseModel):
    """One paper's answer for one comparison aspect."""

    paper_id: UUID
    paper_title: str
    summary: str = Field(..., description="What this paper reports for the aspect.")
    page_number: int | None = Field(
        default=None,
        description="Page the claim was sourced from; None when not attributable.",
    )
    chunk_id: UUID | None = None
    not_reported: bool = Field(
        default=False,
        description="True when the context does not report this aspect for the paper.",
    )


class CompareRow(BaseModel):
    """One row of the comparison matrix (one aspect across all papers)."""

    aspect: str
    cells: list[CompareCell]


class ComparePaperRef(BaseModel):
    """Minimal paper identity used to label matrix columns."""

    paper_id: UUID
    paper_title: str
    publication_year: int | None = None


class CompareResponse(BaseModel):
    """Structured comparison matrix returned to the client."""

    papers: list[ComparePaperRef]
    rows: list[CompareRow]
    summary: str = Field(default="", description="Cross-paper synthesis narrative.")
    citations: list[UUID] = Field(
        default_factory=list,
        description="Chunk IDs backing the matrix cells (traceability).",
    )


# ---------------------------------------------------------------------------
# Literature review (FR-12)
# ---------------------------------------------------------------------------

# The review structure suggested by FR-12. Each entry becomes one section of
# the generated document, in this order.
DEFAULT_REVIEW_SECTIONS: list[str] = [
    "Introduction",
    "Existing Approaches",
    "Methodological Trends",
    "Dataset Trends",
    "Results",
    "Limitations",
    "Research Gaps",
]


class LiteratureReviewRequest(BaseModel):
    """Request body for POST /api/research/literature-review."""

    paper_ids: list[UUID] = Field(
        ...,
        min_length=2,
        max_length=10,
        description="Two to ten papers to synthesize. All must belong to the caller.",
    )
    title: str | None = Field(
        default=None,
        max_length=200,
        description="Optional title for the review; generated when omitted.",
    )
    focus: str | None = Field(
        default=None,
        max_length=1000,
        description="Optional user focus, e.g. 'evaluation methodology'.",
    )
    sections: list[str] | None = Field(
        default=None,
        description="Section headings. Omit to use the FR-12 default structure.",
    )
    per_paper_top_k: int = Field(
        default=8,
        ge=1,
        le=20,
        description="Max context chunks retrieved per paper.",
    )


class ReviewCitation(BaseModel):
    """One source backing a review section."""

    paper_id: UUID
    paper_title: str
    page_number: int | None = None
    chunk_id: UUID | None = None


class ReviewSection(BaseModel):
    """One section of the generated review."""

    heading: str
    content: str = Field(
        default="",
        description="AI-generated synthesis for this section.",
    )
    citations: list[ReviewCitation] = Field(
        default_factory=list,
        description="Sources supporting this section.",
    )
    insufficient_context: bool = Field(
        default=False,
        description=(
            "True when the retrieved context did not support this section, so "
            "the UI can say so instead of presenting a thin section as fact."
        ),
    )


class LiteratureReviewResponse(BaseModel):
    """Structured literature review returned to the client."""

    title: str
    papers: list[ComparePaperRef]
    sections: list[ReviewSection]
    references: list[ComparePaperRef] = Field(
        default_factory=list,
        description="Papers cited in the review, for the references list.",
    )
    citations: list[UUID] = Field(
        default_factory=list,
        description="Chunk IDs backing the review (traceability).",
    )


# ---------------------------------------------------------------------------
# Research gaps (FR-13)
# ---------------------------------------------------------------------------


class GapCategory(str, Enum):
    """The recurring gap types FR-13 asks the system to identify."""

    limitation = "Limitation"
    unresolved_problem = "Unresolved Problem"
    future_work = "Future Work"
    dataset_limitation = "Dataset Limitation"
    methodological_gap = "Methodological Gap"


class GapRequest(BaseModel):
    """Request body for POST /api/research/gaps."""

    paper_ids: list[UUID] = Field(
        ...,
        min_length=1,
        max_length=10,
        description="One to ten papers to analyse. All must belong to the caller.",
    )
    categories: list[GapCategory] | None = Field(
        default=None,
        description="Restrict extraction to these gap types. Omit for all FR-13 types.",
    )
    focus: str | None = Field(
        default=None,
        max_length=1000,
        description="Optional user focus, e.g. 'evaluation and reproducibility'.",
    )
    per_paper_top_k: int = Field(
        default=8,
        ge=1,
        le=20,
        description="Max context chunks retrieved per paper.",
    )


class GapCitation(BaseModel):
    """One source supporting a gap, resolved server-side."""

    paper_id: UUID
    paper_title: str
    page_number: int | None = None
    chunk_id: UUID | None = None


class ResearchGap(BaseModel):
    """A single identified research gap.

    ``evidence`` quotes what the papers actually say; ``observation`` and
    ``suggested_direction`` are AI inference. The separation is what lets
    the UI label the inference honestly (FR-13).
    """

    title: str
    category: GapCategory
    description: str = Field(..., description="The gap itself, in plain language.")
    evidence: str = Field(
        default="",
        description="What the papers state that supports this gap.",
    )
    suggested_direction: str = Field(
        default="",
        description="AI-suggested research direction. Not a paper finding.",
    )
    paper_ids: list[UUID] = Field(
        default_factory=list,
        description="Papers this gap was observed across.",
    )
    citations: list[GapCitation] = Field(default_factory=list)
    recurrence: int = Field(
        default=1,
        ge=1,
        description="How many papers raised this gap. Higher means more recurring.",
    )


class GapCluster(BaseModel):
    """A set of gaps of the same category."""

    category: GapCategory
    gaps: list[ResearchGap] = Field(default_factory=list)


class GapResponse(BaseModel):
    """Structured research-gap analysis returned to the client."""

    papers: list[ComparePaperRef]
    clusters: list[GapCluster] = Field(
        default_factory=list,
        description="Gaps grouped by FR-13 category.",
    )
    summary: str = Field(default="", description="Cross-paper gap overview.")
    citations: list[UUID] = Field(
        default_factory=list,
        description="Chunk IDs backing the identified gaps (traceability).",
    )
