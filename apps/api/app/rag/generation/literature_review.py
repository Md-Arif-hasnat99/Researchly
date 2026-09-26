"""Literature review generation (FR-12).

Produces a structured, multi-section research synthesis from the caller's
own papers. Like the comparison generator, context is grouped **per paper**
so the model can attribute claims and the API can attach real chunk-level
citations.

Flow::

    per-paper chunks  (retrieval)
            ↓
    grouped context block (one section per paper)
            ↓
    grounded Gemini call (JSON schema constrained)
            ↓
    LiteratureReviewResult — ordered sections + references

Grounding rules enforced in the system prompt (FR-12):
- Every section is written only from the supplied context groups.
- Claims trace back to a paper and page; the model returns the indices it
  used and the API maps those to real chunk IDs — citations are never
  invented by the model.
- A section the context cannot support is flagged ``insufficient_context``
  rather than padded with plausible-sounding prose. This is what keeps the
  synthesis distinguishable from direct paper findings.
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
    DEFAULT_REVIEW_SECTIONS,
    ComparePaperRef,
    LiteratureReviewResponse,
    ReviewCitation,
    ReviewSection,
)

logger = logging.getLogger("researchly")

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are ResearchRAG, an AI research assistant that writes structured \
literature reviews from scientific papers.

You will receive context excerpts grouped by paper. Each group is labelled \
with that paper's number and title.

Rules you MUST follow:
1. Base every statement ONLY on the supplied context. Never introduce \
   knowledge that is not in the context, and never cite a paper that was \
   not supplied.
2. Write in third person, academic register. Prefer concrete specifics \
   (dataset names, metric names, reported numbers) over vague description.
3. This is a SYNTHESIS across papers, not a summary of one. Identify \
   agreements, disagreements, and chronological or conceptual trends \
   across the supplied papers.
4. For each section, list the paper indices you actually drew on in \
   "paper_indices". Only include indices you genuinely used.
5. If the context does not support a section, set \
   "insufficient_context" to true and leave "content" empty. Do NOT pad \
   the section with general knowledge or speculation. An empty, flagged \
   section is correct and expected behaviour.
6. Do not fabricate results, numbers, or claims that the context does not \
   state.

Return a single JSON object matching the provided schema. Output no prose \
outside the JSON.
"""

# Sentinels for sections the model could not ground.
_EMPTY_CONTENT = "The retrieved context did not provide enough material to write this section."


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class LiteratureReviewResult:
    """Result of a literature review generation run."""

    title: str
    papers: list[ComparePaperRef]
    sections: list[ReviewSection]
    references: list[ComparePaperRef] = field(default_factory=list)
    citations: list[UUID] = field(default_factory=list)

    @property
    def citation_count(self) -> int:
        return len(self.citations)

    def to_response(self) -> LiteratureReviewResponse:
        """Project the internal result onto the public API schema."""
        return LiteratureReviewResponse(
            title=self.title,
            papers=self.papers,
            sections=self.sections,
            references=self.references,
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


def _response_schema(sections: list[str]) -> dict:
    """Build a JSON schema constraining the model to the requested sections."""
    return {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "sections": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "heading": {"type": "string", "enum": sections},
                        "content": {"type": "string"},
                        "paper_indices": {
                            "type": "array",
                            "items": {"type": "integer"},
                        },
                        "insufficient_context": {"type": "boolean"},
                    },
                    "required": ["heading", "content"],
                },
            },
        },
        "required": ["title", "sections"],
        "propertyOrdering": ["title", "sections"],
        "_comment": f"Exactly {len(sections)} sections, one per requested heading.",
    }


def _build_prompt(
    contexts: list[PaperContext],
    sections: list[str],
    title: str | None,
    focus: str | None,
) -> str:
    """Assemble the user-turn prompt."""
    paper_lines = "\n".join(
        f"PAPER {idx} = {ctx.paper_title}"
        for idx, ctx in enumerate(contexts, start=1)
    )
    requested_title = f"\nRequested title: {title}\n" if title else ""
    focus_line = f"\nUser focus: {focus}\n" if focus else ""

    return (
        f"Papers to synthesize (use these exact indices):\n{paper_lines}\n"
        f"\nRequired sections, in this order: {', '.join(sections)}\n"
        f"{requested_title}{focus_line}"
        f"\nContext excerpts:\n{_build_context_block(contexts)}\n"
        f"\n---\n"
        f"Write the structured literature review as JSON."
    )


def _parse_sections(
    raw_text: str,
    contexts: list[PaperContext],
    sections: list[str],
) -> tuple[str, list[ReviewSection]]:
    """Parse the model JSON into ordered sections with resolved citations.

    Every requested heading is present in the output even when the model
    omitted it, so the document structure is stable. Paper indices supplied
    by the model are mapped to real chunk IDs from the retrieved context —
    the model never invents an identifier.
    """
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError:
        logger.warning("Literature review response was not valid JSON; degrading to stubs.")
        payload = {}

    by_index = {idx: ctx for idx, ctx in enumerate(contexts, start=1)}
    raw_sections: dict[str, dict] = {}
    for raw in payload.get("sections", []):
        if isinstance(raw, dict) and raw.get("heading"):
            raw_sections[str(raw["heading"])] = raw

    parsed: list[ReviewSection] = []
    for heading in sections:
        raw = raw_sections.get(heading, {})
        content = str(raw.get("content") or "").strip()
        flagged = bool(raw.get("insufficient_context")) or not content

        if flagged:
            parsed.append(
                ReviewSection(
                    heading=heading,
                    content=_EMPTY_CONTENT,
                    citations=[],
                    insufficient_context=True,
                )
            )
            continue

        citations: list[ReviewCitation] = []
        seen: set[tuple[UUID, int | None]] = set()
        for index in raw.get("paper_indices", []) or []:
            try:
                ctx = by_index.get(int(index))
            except (TypeError, ValueError):
                continue
            if ctx is None:
                continue
            # Attribute the section to the first retrieved chunk of each paper
            # it drew on; the section text is a synthesis, not a single page.
            page, _content, chunk_id = ctx.chunks[0] if ctx.chunks else (None, "", None)
            key = (ctx.paper_id, page)
            if key in seen:
                continue
            seen.add(key)
            citations.append(
                ReviewCitation(
                    paper_id=ctx.paper_id,
                    paper_title=ctx.paper_title,
                    page_number=page,
                    chunk_id=chunk_id,
                )
            )

        parsed.append(
            ReviewSection(
                heading=heading,
                content=content,
                citations=citations,
                insufficient_context=False,
            )
        )

    title = payload.get("title")
    return str(title).strip() if isinstance(title, str) and title.strip() else "", parsed


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_literature_review(
    contexts: list[PaperContext],
    sections: list[str] | None = None,
    title: str | None = None,
    focus: str | None = None,
) -> LiteratureReviewResult:
    """Generate a grounded, structured literature review.

    Args:
        contexts: Per-paper retrieved context. Must contain at least two
                  papers; only papers with retrieved chunks are used.
        sections: Section headings. Defaults to
                  :data:`DEFAULT_REVIEW_SECTIONS` (FR-12).
        title:    Optional user-supplied title.
        focus:    Optional user focus string steering the synthesis.

    Returns:
        :class:`LiteratureReviewResult` with ordered sections, per-section
        citations, and a references list.

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
            f"for a literature review (got {len(usable)})."
        )

    settings = get_settings()
    if not settings.GEMINI_API_KEY:
        raise RuntimeError(
            "GEMINI_API_KEY is not configured. "
            "Set it in your .env file to enable literature review generation."
        )

    section_list = [s.strip() for s in (sections or DEFAULT_REVIEW_SECTIONS) if s and s.strip()]
    if not section_list:
        section_list = list(DEFAULT_REVIEW_SECTIONS)

    prompt = _build_prompt(usable, section_list, title, focus)

    client = genai.Client(api_key=settings.GEMINI_API_KEY)
    model = settings.GEMINI_GENERATION_MODEL

    logger.info(
        "Generating literature review | model=%s papers=%d sections=%d",
        model,
        len(usable),
        len(section_list),
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
            response_schema=_response_schema(section_list),
        ),
    )

    generated_title, parsed_sections = _parse_sections(
        response.text or "", usable, section_list
    )

    papers = [
        ComparePaperRef(
            paper_id=ctx.paper_id,
            paper_title=ctx.paper_title,
            publication_year=ctx.publication_year,
        )
        for ctx in usable
    ]

    # References: only papers actually cited by at least one grounded section.
    cited_paper_ids: list[UUID] = []
    for section in parsed_sections:
        for citation in section.citations:
            if citation.paper_id not in cited_paper_ids:
                cited_paper_ids.append(citation.paper_id)
    references = [p for p in papers if p.paper_id in cited_paper_ids]

    cited_chunks: list[UUID] = []
    for section in parsed_sections:
        for citation in section.citations:
            if citation.chunk_id is not None and citation.chunk_id not in cited_chunks:
                cited_chunks.append(citation.chunk_id)

    return LiteratureReviewResult(
        title=generated_title or title or f"Literature Review ({len(usable)} papers)",
        papers=papers,
        sections=parsed_sections,
        references=references,
        citations=cited_chunks,
    )
