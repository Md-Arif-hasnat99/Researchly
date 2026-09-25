"""Grounded answer generation using Gemini.

Receives a user query and the retrieved context chunks, builds a
grounded prompt, calls Gemini, and returns a plain-text answer.

Grounding rules (enforced in the system prompt):
- Use only information from the supplied context.
- Never fabricate citations — reference only provided [N] labels.
- If the answer is not in the context, say so explicitly.
- Always cite sources with [N] inline references.

The returned :class:`GeneratedAnswer` carries both the answer text
and a mapping from citation index → source chunk so the caller can
persist ``citations`` rows.
"""

import logging
from dataclasses import dataclass, field

import google.genai as genai
import google.genai.types as genai_types

from app.core.config import get_settings
from app.schemas.search import SearchResultChunk

logger = logging.getLogger("researchly")

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are ResearchRAG, an AI research assistant that answers questions \
strictly using the provided scientific paper excerpts.

Rules you MUST follow:
1. Base every claim ONLY on the context excerpts below. \
   Do not use outside knowledge.
2. Cite sources inline using bracketed numbers, e.g. [1], [2].
3. If the answer cannot be found in the context, say: \
   "I could not find information about this in the provided papers."
4. Never invent citations or quote text that is not in the context.
5. Be concise but thorough. Use bullet points or short paragraphs \
   as appropriate.
"""


@dataclass
class GeneratedAnswer:
    """Result of a single RAG generation call."""

    answer: str
    """The model's grounded answer text (may include [N] citation markers)."""

    cited_chunks: list[SearchResultChunk] = field(default_factory=list)
    """Chunks that were included in the context (ordered as [1], [2], …)."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_context_block(chunks: list[SearchResultChunk]) -> str:
    """Format retrieved chunks as a numbered context block for the prompt."""
    lines: list[str] = []
    for i, chunk in enumerate(chunks, start=1):
        header = (
            f"[{i}] {chunk.paper_title}"
            f" — page {chunk.page_number}"
            + (f", {chunk.section}" if chunk.section else "")
        )
        lines.append(f"{header}\n{chunk.content}")
    return "\n\n".join(lines)


def _build_prompt(query: str, context_block: str) -> str:
    """Assemble the full user-turn prompt."""
    return (
        f"Context from research papers:\n\n"
        f"{context_block}\n\n"
        f"---\n\n"
        f"Question: {query}\n\n"
        f"Answer (cite sources with [N]):"
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_answer(
    query: str,
    chunks: list[SearchResultChunk],
) -> GeneratedAnswer:
    """Generate a grounded answer for *query* using *chunks* as context.

    Args:
        query:  The user's natural-language question.
        chunks: Retrieved chunks (from :func:`similarity_search`), already
                ordered by similarity descending.

    Returns:
        :class:`GeneratedAnswer` with the model's response and the context
        chunks that were supplied (for citation persistence).

    Raises:
        RuntimeError: If GEMINI_API_KEY is not configured.
        Exception:    Propagated from the Gemini SDK on API failure.
    """
    settings = get_settings()
    if not settings.GEMINI_API_KEY:
        raise RuntimeError(
            "GEMINI_API_KEY is not configured. "
            "Set it in your .env file to enable answer generation."
        )

    if not chunks:
        logger.info("No context chunks — returning fallback answer.")
        return GeneratedAnswer(
            answer=(
                "I could not find information about this in the provided papers. "
                "Please try uploading relevant papers or rephrasing your question."
            ),
            cited_chunks=[],
        )

    context_block = _build_context_block(chunks)
    prompt = _build_prompt(query, context_block)

    client = genai.Client(api_key=settings.GEMINI_API_KEY)
    model = settings.GEMINI_GENERATION_MODEL

    logger.info(
        "Generating answer | model=%s chunks=%d query=%r",
        model,
        len(chunks),
        query[:80],
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
            temperature=0.2,       # low temperature for factual grounding
            max_output_tokens=2048,
        ),
    )

    answer_text: str = response.text or ""
    logger.info("Generation complete — %d chars", len(answer_text))

    return GeneratedAnswer(answer=answer_text, cited_chunks=chunks)
