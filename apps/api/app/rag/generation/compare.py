"""Multi-paper comparison generation (FR-11).

Builds a structured comparison matrix from retrieved context chunks.
Unlike single-paper RAG, the context is grouped **per paper** so the
model must attribute each cell to exactly one paper — this is what
preserves source identity across papers (architecture.md §14).

Flow::

    per-paper chunks  (retrieval)
            ↓
    grouped context block (one section per paper)
            ↓
    grounded Gemini call (JSON schema constrained)
            ↓
    ComparisonResult  — rows of cells + summary, no invented citations

Grounding rules enforced in the system prompt:
- Each cell is filled only from that paper's own context section.
- If the context does not report the aspect, the cell is marked
  ``not_reported`` rather than guessed.
- Never reference papers that were not supplied.
"""

import json
import logging
from dataclasses import dataclass, field
from uuid import UUID

import google.genai as genai
import google.genai.types as genai_types

from app.core.config import get_settings
from app.schemas.research import (
    DEFAULT_ASPECTS,
    CompareCell,
    ComparePaperRef,
    CompareRow,
)

logger = logging.getLogger("researchly")

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are ResearchRAG, an AI research assistant that compares scientific papers.

You will receive context excerpts grouped by paper. Each group is labelled \
with that paper's number and title.

Rules you MUST follow:
1. For every aspect and every paper, use ONLY that paper's own context \
   group. Never borrow facts from another paper.
2. If a paper's context does not report an aspect, set that cell's \
   "not_reported" to true and set "summary" to "Not reported in the \
   available context." Do not guess or infer.
3. Keep each cell summary factual and concise (one or two sentences). \
   Include concrete numbers, dataset names, or metric names when the \
   context provides them.
4. After the matrix, write a "summary": a short cross-paper synthesis \
   (2-4 sentences) highlighting the most important similarities and \
   differences. This summary is an AI synthesis, not a paper finding.
5. Use "page_number" to record the page the cell was sourced from, or \
   null when not attributable from the context.

Return a single JSON object matching the provided schema. Output no prose \
outside the JSON.
"""

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class PaperContext:
    """One paper's retrieved context used to fill its matrix column."""

    paper_id: UUID
    paper_title: str
    publication_year: int | None
    chunks: list[tuple[int, str, UUID]] = field(default_factory=list)
    """(page_number, content, chunk_id) triples."""


@dataclass
class ComparisonResult:
    """Result of a multi-paper comparison run."""

    papers: list[ComparePaperRef]
    rows: list[CompareRow]
    summary: str = ""
    citations: list[UUID] = field(default_factory=list)

    @property
    def citation_count(self) -> int:
        return len(self.citations)


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


def _response_schema(paper_count: int, aspects: list[str]) -> dict:
    """Build a JSON schema constraining the model to a fixed matrix shape."""
    return {
        "type": "object",
        "properties": {
            "rows": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "aspect": {"type": "string", "enum": aspects},
                        "cells": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "paper_index": {"type": "integer"},
                                    "summary": {"type": "string"},
                                    "page_number": {"type": "integer"},
                                    "not_reported": {"type": "boolean"},
                                },
                                "required": ["paper_index", "summary"],
                            },
                        },
                    },
                    "required": ["aspect", "cells"],
                },
            },
            "summary": {"type": "string"},
        },
        "required": ["rows", "summary"],
        "propertyOrdering": ["rows", "summary"],
        "_comment": f"Exactly {len(aspects)} rows and {paper_count} cells per row.",
    }


def _build_prompt(
    contexts: list[PaperContext],
    aspects: list[str],
    focus: str | None,
) -> str:
    """Assemble the user-turn prompt."""
    paper_lines = "\n".join(
        f"PAPER {idx} = {ctx.paper_title}"
        for idx, ctx in enumerate(contexts, start=1)
    )
    focus_line = f"\nUser focus: {focus}\n" if focus else ""

    return (
        f"Papers to compare (use these exact indices):\n{paper_lines}\n"
        f"\nAspects (rows of the matrix): {', '.join(aspects)}\n"
        f"{focus_line}"
        f"\nContext excerpts:\n{_build_context_block(contexts)}\n"
        f"\n---\n"
        f"Build the comparison matrix and the cross-paper summary as JSON."
    )


def _parse_matrix(
    raw_text: str,
    contexts: list[PaperContext],
    aspects: list[str],
) -> tuple[list[CompareRow], str]:
    """Parse the model's JSON into rows, filling gaps defensively.

    Missing or malformed cells become ``not_reported`` cells so the matrix
    always has one cell per (aspect, paper) pair.
    """
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError:
        logger.warning("Comparison response was not valid JSON; degrading to empty matrix.")
        payload = {}

    by_index = {idx: ctx for idx, ctx in enumerate(contexts, start=1)}
    rows: list[CompareRow] = []

    for aspect in aspects:
        raw_row = next(
            (r for r in payload.get("rows", []) if r.get("aspect") == aspect),
            None,
        )
        raw_cells: dict[int, dict] = {}
        if raw_row:
            for cell in raw_row.get("cells", []):
                try:
                    raw_cells[int(cell.get("paper_index"))] = cell
                except (TypeError, ValueError):
                    continue

        cells: list[CompareCell] = []
        for idx, ctx in by_index.items():
            raw = raw_cells.get(idx, {})
            not_reported = bool(raw.get("not_reported")) or idx not in raw_cells
            page = raw.get("page_number")
            cells.append(
                CompareCell(
                    paper_id=ctx.paper_id,
                    paper_title=ctx.paper_title,
                    summary=str(raw.get("summary") or "")
                    if not not_reported
                    else "Not reported in the available context.",
                    page_number=page if isinstance(page, int) else None,
                    chunk_id=_chunk_id_for_page(ctx, page),
                    not_reported=not_reported,
                )
            )
        rows.append(CompareRow(aspect=aspect, cells=cells))

    summary = payload.get("summary")
    return rows, str(summary) if isinstance(summary, str) else ""


def _chunk_id_for_page(ctx: PaperContext, page: int | None) -> UUID | None:
    """Return the chunk ID backing a given page, when known."""
    if not isinstance(page, int):
        return None
    for chunk_page, _content, chunk_id in ctx.chunks:
        if chunk_page == page:
            return chunk_id
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_comparison(
    contexts: list[PaperContext],
    aspects: list[str] | None = None,
    focus: str | None = None,
) -> ComparisonResult:
    """Generate a grounded multi-paper comparison matrix.

    Args:
        contexts: Per-paper retrieved context. Must contain at least two
                  papers; only papers with retrieved chunks are returned.
        aspects:  Comparison aspects (rows). Defaults to
                  :data:`DEFAULT_ASPECTS`.
        focus:    Optional user focus string steering the synthesis.

    Returns:
        :class:`ComparisonResult` with a complete matrix and summary.

    Raises:
        ValueError:   If fewer than two papers have retrieved context.
        RuntimeError: If GEMINI_API_KEY is not configured.
        Exception:    Propagated from the Gemini SDK on API failure.
    """
    # Argument validation precedes configuration checks so callers get a
    # precise 422 for a bad request rather than a 503 for missing config.
    usable = [ctx for ctx in contexts if ctx.chunks]
    if len(usable) < 2:
        raise ValueError(
            "At least two papers with retrieved context are required "
            f"for a comparison (got {len(usable)})."
        )

    settings = get_settings()
    if not settings.GEMINI_API_KEY:
        raise RuntimeError(
            "GEMINI_API_KEY is not configured. "
            "Set it in your .env file to enable comparison generation."
        )

    aspect_list = [a.strip() for a in (aspects or DEFAULT_ASPECTS) if a and a.strip()]
    if not aspect_list:
        aspect_list = list(DEFAULT_ASPECTS)

    prompt = _build_prompt(usable, aspect_list, focus)

    client = genai.Client(api_key=settings.GEMINI_API_KEY)
    model = settings.GEMINI_GENERATION_MODEL

    logger.info(
        "Generating comparison | model=%s papers=%d aspects=%d",
        model,
        len(usable),
        len(aspect_list),
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
            temperature=0.2,
            max_output_tokens=4096,
            response_mime_type="application/json",
            response_schema=_response_schema(len(usable), aspect_list),
        ),
    )

    rows, summary = _parse_matrix(response.text or "", usable, aspect_list)

    cited: list[UUID] = []
    for row in rows:
        for cell in row.cells:
            if cell.chunk_id is not None and cell.chunk_id not in cited:
                cited.append(cell.chunk_id)

    return ComparisonResult(
        papers=[
            ComparePaperRef(
                paper_id=ctx.paper_id,
                paper_title=ctx.paper_title,
                publication_year=ctx.publication_year,
            )
            for ctx in usable
        ],
        rows=rows,
        summary=summary,
        citations=cited,
    )
