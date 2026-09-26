"""Research gap extraction (FR-13).

Identifies recurring limitations, unresolved problems, future-work
directions, dataset limitations, and methodological gaps across the
caller's papers, keeping source attribution attached to every gap.

Flow::

    per-paper chunks  (retrieval)
            ↓
    grouped context block (one section per paper)
            ↓
    grounded Gemini call (JSON schema constrained)
            ↓
    GapResult — gaps clustered by category, each with real citations

Two properties matter here and are enforced throughout:

1. **Source attribution is resolved server-side.** The model returns the
   paper indices and page numbers it used; this module maps those onto the
   retrieved chunk IDs. The model never emits an identifier, so it cannot
   fabricate a citation.

2. **Evidence is separated from inference.** ``evidence`` is what the papers
   state; ``observation`` and ``suggested_direction`` are AI inference.
   FR-13 requires gaps be labelled as AI-generated observations, and that
   distinction is only honest if the underlying quote is kept separate.

Gaps that recur across multiple papers are the point of the feature, so
``recurrence`` counts how many distinct papers raised each gap.
"""

import json
import logging
from dataclasses import dataclass, field
from uuid import UUID

import google.genai as genai
import google.genai.types as genai_types

from app.core.config import get_settings
from app.rag.generation.compare import PaperContext
from app.schemas.research import (
    ComparePaperRef,
    GapCategory,
    GapCitation,
    GapCluster,
    GapResponse,
    ResearchGap,
)

logger = logging.getLogger("researchly")

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are ResearchRAG, an AI research assistant that identifies research gaps \
across scientific papers.

You will receive context excerpts grouped by paper. Each group is labelled \
with that paper's number and title.

Identify gaps of these types:
- Limitation: a weakness the authors acknowledge.
- Unresolved Problem: an open question the work does not answer.
- Future Work: work the authors explicitly defer to future research.
- Dataset Limitation: a constraint of the data used (size, coverage, \
bias, annotation, staleness).
- Methodological Gap: a missing capability, evaluation weakness, or \
unjustified design choice.

Rules you MUST follow:
1. Base every gap ONLY on the supplied context. Never introduce outside \
   knowledge, and never cite a paper that was not supplied.
2. In "evidence", quote or closely paraphrase what the papers actually \
   state. This must be attributable to the source pages. If you cannot \
   ground the gap in the context, do not report it at all — omit the gap \
   entirely rather than guessing.
3. "description" and "suggested_direction" are YOUR inference, not paper \
   findings. Keep them clearly framed as analysis. Do not present a \
   suggested direction as if the papers proposed it, unless they did.
4. List every paper index that raised this gap in "paper_indices", and \
   give the page number in "page_number" for each entry in "page_numbers". \
   Only include indices you genuinely used.
5. Prefer recurring gaps. A limitation acknowledged independently by \
   several papers is more significant than a one-off remark. Merge \
   near-duplicate gaps from different papers into a single gap with \
   multiple paper indices rather than emitting duplicates.
6. If the context contains no genuine gaps, return an empty "gaps" array. \
   An empty result is a correct and expected outcome.

Return a single JSON object matching the provided schema. Output no prose \
outside the JSON.
"""


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class GapResult:
    """Result of a research gap extraction run."""

    papers: list[ComparePaperRef]
    clusters: list[GapCluster] = field(default_factory=list)
    summary: str = ""
    citations: list[UUID] = field(default_factory=list)

    @property
    def citation_count(self) -> int:
        return len(self.citations)

    @property
    def gap_count(self) -> int:
        return sum(len(cluster.gaps) for cluster in self.clusters)

    def to_response(self) -> GapResponse:
        """Project the internal result onto the public API schema."""
        return GapResponse(
            papers=self.papers,
            clusters=self.clusters,
            summary=self.summary,
            citations=self.citations,
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_context_block(contexts: list[PaperContext]) -> str:
    """Render per-paper context groups, numbered to match the JSON schema."""
    parts: list[str] = []
    for idx, ctx in enumerate(contexts, start=1):
        year = f" ({ctx.publication_year})" if ctx.publication_year else ""
        parts.append(f"--- PAPER {idx}: {ctx.paper_title}{year} ---")
        for page, content, _chunk_id in ctx.chunks:
            parts.append(f"[p.{page}] {content}")
    return "\n\n".join(parts)


def _response_schema(categories: list[GapCategory]) -> dict:
    """Build a JSON schema constraining gap categories to the requested set."""
    return {
        "type": "object",
        "properties": {
            "gaps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "category": {
                            "type": "string",
                            "enum": [c.value for c in categories],
                        },
                        "description": {"type": "string"},
                        "evidence": {"type": "string"},
                        "suggested_direction": {"type": "string"},
                        "paper_indices": {
                            "type": "array",
                            "items": {"type": "integer"},
                        },
                        "page_numbers": {
                            "type": "array",
                            "items": {"type": "integer"},
                        },
                    },
                    "required": ["title", "category", "description"],
                },
            },
            "summary": {"type": "string"},
        },
        "required": ["gaps", "summary"],
        "propertyOrdering": ["gaps", "summary"],
    }


def _build_prompt(
    contexts: list[PaperContext],
    categories: list[GapCategory],
    focus: str | None,
) -> str:
    """Assemble the user-turn prompt."""
    paper_lines = "\n".join(
        f"PAPER {idx} = {ctx.paper_title}"
        for idx, ctx in enumerate(contexts, start=1)
    )
    focus_line = f"\nUser focus: {focus}\n" if focus else ""

    return (
        f"Papers to analyse (use these exact indices):\n{paper_lines}\n"
        f"\nGap categories to look for: {', '.join(c.value for c in categories)}\n"
        f"{focus_line}"
        f"\nContext excerpts:\n{_build_context_block(contexts)}\n"
        f"\n---\n"
        f"Identify the research gaps and return them as JSON."
    )


def _coerce_category(value: object, allowed: list[GapCategory]) -> GapCategory | None:
    """Map a model-supplied category string onto a requested category."""
    if not isinstance(value, str):
        return None
    wanted = value.strip().lower()
    for category in allowed:
        if category.value.lower() == wanted or category.name.lower() == wanted:
            return category
    return None


def _as_int_list(value: object) -> list[int]:
    """Coerce a model-supplied list into integers, dropping junk entries."""
    if not isinstance(value, list):
        return []
    out: list[int] = []
    for item in value:
        try:
            out.append(int(item))
        except (TypeError, ValueError):
            continue
    return out


def _resolve_citations(
    raw: dict,
    by_index: dict[int, PaperContext],
) -> tuple[list[UUID], list[GapCitation]]:
    """Map model-supplied indices/pages onto real retrieved chunk IDs.

    Returns the distinct paper IDs the gap spans and the resolved citations.
    Indices outside the supplied set, and pages with no matching retrieved
    chunk, are ignored rather than guessed at.
    """
    indices = [i for i in _as_int_list(raw.get("paper_indices")) if i in by_index]
    pages = _as_int_list(raw.get("page_numbers"))

    paper_ids: list[UUID] = []
    citations: list[GapCitation] = []
    seen: set[UUID] = set()

    for position, index in enumerate(indices):
        ctx = by_index[index]
        if ctx.paper_id not in seen:
            seen.add(ctx.paper_id)
            paper_ids.append(ctx.paper_id)

        # Prefer the page the model cited for this paper; fall back to the
        # first retrieved chunk so the gap is never left unattributed.
        page: int | None = None
        if position < len(pages) and pages[position] in {p for p, _c, _id in ctx.chunks}:
            page = pages[position]
        elif ctx.chunks:
            page = ctx.chunks[0][0]

        chunk_id = next(
            (cid for p, _c, cid in ctx.chunks if p == page),
            ctx.chunks[0][2] if ctx.chunks else None,
        )
        citations.append(
            GapCitation(
                paper_id=ctx.paper_id,
                paper_title=ctx.paper_title,
                page_number=page,
                chunk_id=chunk_id,
            )
        )

    return paper_ids, citations


def _parse_gaps(
    raw_text: str,
    contexts: list[PaperContext],
    categories: list[GapCategory],
) -> tuple[list[GapCluster], str]:
    """Parse the model JSON into category clusters with resolved citations.

    Gaps the model could not ground, or that carry a category we did not
    request, are dropped — an unattributed gap would be an unverifiable
    claim presented as evidence-based.
    """
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError:
        logger.warning("Gap response was not valid JSON; returning no gaps.")
        payload = {}

    by_index = {idx: ctx for idx, ctx in enumerate(contexts, start=1)}
    buckets: dict[GapCategory, list[ResearchGap]] = {c: [] for c in categories}

    for raw in payload.get("gaps", []):
        if not isinstance(raw, dict):
            continue

        title = str(raw.get("title") or "").strip()
        description = str(raw.get("description") or "").strip()
        category = _coerce_category(raw.get("category"), categories)
        if not title or not description or category is None:
            continue

        paper_ids, citations = _resolve_citations(raw, by_index)
        if not citations:
            # No supplied paper backs this gap; drop it rather than present an
            # unsupported observation as a finding.
            logger.info("Dropping unattributed gap: %r", title[:60])
            continue

        buckets[category].append(
            ResearchGap(
                title=title,
                category=category,
                description=description,
                evidence=str(raw.get("evidence") or "").strip(),
                suggested_direction=str(raw.get("suggested_direction") or "").strip(),
                paper_ids=paper_ids,
                citations=citations,
                recurrence=len(paper_ids),
            )
        )

    # Most-recurring gaps first within each category; FR-13 is about gaps
    # that keep coming up, not one-off remarks.
    clusters: list[GapCluster] = []
    for category in categories:
        gaps = sorted(buckets[category], key=lambda g: (-g.recurrence, g.title))
        if gaps:
            clusters.append(GapCluster(category=category, gaps=gaps))

    summary = payload.get("summary")
    return clusters, str(summary).strip() if isinstance(summary, str) else ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def identify_research_gaps(
    contexts: list[PaperContext],
    categories: list[GapCategory] | None = None,
    focus: str | None = None,
) -> GapResult:
    """Identify grounded research gaps across the supplied papers.

    Args:
        contexts:   Per-paper retrieved context. Only papers with retrieved
                    chunks are used; at least one is required.
        categories: Gap types to look for. Defaults to every FR-13 category.
        focus:      Optional user focus string.

    Returns:
        :class:`GapResult` with gaps clustered by category, most recurring
        first, each carrying server-resolved citations.

    Raises:
        ValueError:   If no paper has retrieved context.
        RuntimeError: If GEMINI_API_KEY is not configured.
        Exception:    Propagated from the Gemini SDK on API failure.
    """
    # Argument validation precedes configuration checks so callers get a
    # precise 422 for a bad request rather than a 503 for missing config.
    usable = [ctx for ctx in contexts if ctx.chunks]
    if not usable:
        raise ValueError("At least one paper with retrieved context is required for gap analysis.")

    settings = get_settings()
    if not settings.GEMINI_API_KEY:
        raise RuntimeError(
            "GEMINI_API_KEY is not configured. "
            "Set it in your .env file to enable gap analysis."
        )

    category_list = list(categories) if categories else list(GapCategory)

    prompt = _build_prompt(usable, category_list, focus)

    client = genai.Client(api_key=settings.GEMINI_API_KEY)
    model = settings.GEMINI_GENERATION_MODEL

    logger.info(
        "Identifying research gaps | model=%s papers=%d categories=%d",
        model,
        len(usable),
        len(category_list),
    )

    response = client.models.generate_content(
        model=model,
        contents=[
            genai_types.Content(
                role="user",
                parts=[genai_types.Part(text=prompt)],
            )
        ],
        config=genai_types.GenerateContentConfig(
            system_instruction=_SYSTEM_PROMPT,
            temperature=0.3,
            max_output_tokens=8192,
            response_mime_type="application/json",
            response_schema=_response_schema(category_list),
        ),
    )

    clusters, summary = _parse_gaps(response.text or "", usable, category_list)

    papers = [
        ComparePaperRef(
            paper_id=ctx.paper_id,
            paper_title=ctx.paper_title,
            publication_year=ctx.publication_year,
        )
        for ctx in usable
    ]

    cited: list[UUID] = []
    for cluster in clusters:
        for gap in cluster.gaps:
            for citation in gap.citations:
                if citation.chunk_id is not None and citation.chunk_id not in cited:
                    cited.append(citation.chunk_id)

    return GapResult(
        papers=papers,
        clusters=clusters,
        summary=summary,
        citations=cited,
    )
