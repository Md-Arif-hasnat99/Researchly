"""Grounded answer generation using Gemini.

Receives a user query and the retrieved context chunks, builds a
grounded prompt, and calls Gemini.

Grounding rules (enforced in the system prompt):
- Use only information from the supplied context.
- Never fabricate citations — reference only provided [N] labels.
- If the answer is not in the context, say so explicitly.
- Always cite sources with [N] inline references.
- Be concise but thorough. Write in Markdown so the answer renders as
  prose: short paragraphs, bullet or numbered lists for enumerations,
  and **bold** for key terms or lead-ins. Do not use large headings,
  code fences, or tables unless the question asks for them.

The returned :class:`GeneratedAnswer` carries both the answer text
and a mapping from citation index → source chunk so the caller can
persist ``citations`` rows.
"""

import logging
import time
from collections.abc import Iterator
from dataclasses import dataclass, field

import google.genai as genai
import google.genai.types as genai_types

from app.core.config import get_settings
from app.core.retry import is_transient, with_retry
from app.schemas.search import SearchResultChunk

logger = logging.getLogger("researchly")

# Module-level cached Gemini client to avoid re-instantiation on each request
_gemini_client: genai.Client | None = None


def _get_gemini_client() -> genai.Client:
    """Return a cached Gemini client instance."""
    global _gemini_client
    if _gemini_client is None:
        settings = get_settings()
        _gemini_client = genai.Client(api_key=settings.GEMINI_API_KEY)
        logger.info("Gemini client initialized.")
    return _gemini_client


def _reset_gemini_client() -> None:
    """Reset the cached Gemini client (for testing only)."""
    global _gemini_client
    if _gemini_client is not None:
        _gemini_client = None
        logger.debug("Gemini client cache cleared.")


# Retry configuration for the streaming path, which retries only while no
# output has been emitted (see stream_answer).
_MAX_RETRIES = 3
_BASE_DELAY_S = 1.0

# HTTP statuses that are considered transient and worth retrying.
_TRANSIENT_CODES = frozenset({408, 429, 500, 502, 503, 504})


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
5. Be concise but thorough. Write in Markdown so the answer renders as \
   prose: short paragraphs, bullet or numbered lists for enumerations, \
   and **bold** for key terms or lead-ins. Do not use large headings, \
   code fences, or tables unless the question asks for them.
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


_NO_CONTEXT_ANSWER = (
    "I could not find information about this in the provided papers. "
    "Please try uploading relevant papers or rephrasing your question."
)


def _generation_config() -> genai_types.GenerateContentConfig:
    """The generation config shared by the buffered and streaming paths."""
    return genai_types.GenerateContentConfig(
        system_instruction=_SYSTEM_PROMPT,
        temperature=0.2,       # low temperature for factual grounding
        max_output_tokens=2048,
    )


def _require_api_key() -> None:
    settings = get_settings()
    if not settings.GEMINI_API_KEY:
        raise RuntimeError(
            "GEMINI_API_KEY is not configured. "
            "Set it in your .env file to enable answer generation."
        )


def _is_transient_error(exc: BaseException) -> bool:
    """Return True if *exc* looks like a transient provider error worth retrying."""
    code = getattr(exc, "code", None)
    if isinstance(code, int) and code in _TRANSIENT_CODES:
        return True
    # Also check error message for common patterns
    msg = str(exc).lower()
    return any(
        kw in msg
        for kw in ("rate limit", "quota", "capacity", "unavailable", "overloaded", "timeout")
    )


def _is_quota_exceeded(exc: BaseException) -> bool:
    """Whether *exc* is a quota/rate-limit refusal (HTTP 429).

    The provider's response carries its own backoff ("Please retry in
    Ns"), so client-side retries cannot succeed — they only spend more
    quota and make the user wait longer for the same refusal.
    """
    if getattr(exc, "code", None) == 429:
        return True
    msg = str(exc).lower()
    return (
        "rate limit" in msg or "quota" in msg or "resource_exhausted" in msg
    )


def _retryable_generation_error(exc: BaseException) -> bool:
    """Whether a failed generation call is worth one more attempt.

    Quota errors are excluded on purpose (see :func:`_is_quota_exceeded`):
    retrying them burns quota for an answer that cannot come back yet.
    """
    return is_transient(exc) and not _is_quota_exceeded(exc)


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
    # Answered before the key check for the same reason as the streaming
    # path: this response never reaches Gemini, so it must not depend on
    # a key being configured.
    if not chunks:
        logger.info("No context chunks — returning fallback answer.")
        return GeneratedAnswer(answer=_NO_CONTEXT_ANSWER, cited_chunks=[])

    _require_api_key()

    context_block = _build_context_block(chunks)
    prompt = _build_prompt(query, context_block)

    settings = get_settings()
    client = _get_gemini_client()
    model = settings.GEMINI_GENERATION_MODEL

    logger.info(
        "Generating answer | model=%s chunks=%d query=%r",
        model,
        len(chunks),
        query[:80],
    )

    try:
        response = with_retry(
            lambda: client.models.generate_content(
                model=model,
                contents=[
                    genai_types.Content(
                        role="user",
                        parts=[genai_types.Part(text=prompt)],
                    )
                ],
                config=_generation_config(),
            ),
            retry_on=_retryable_generation_error,
            label="answer generation",
        )

        answer_text: str = response.text or ""
        logger.info("Generation complete — %d chars", len(answer_text))

        return GeneratedAnswer(answer=answer_text, cited_chunks=chunks)

    except Exception as exc:  # noqa: BLE001
        logger.error("Generation failed: %s", exc)
        raise


def stream_answer(
    query: str,
    chunks: list[SearchResultChunk],
) -> Iterator[str]:
    """Generate a grounded answer, yielding text as the model produces it.

    Yields the same text :func:`generate_answer` would have returned
    whole, but incrementally, so the caller can show the first tokens
    while Gemini is still writing the rest.

    Retry policy differs from the buffered path on purpose. A stream that
    has already emitted text cannot be safely restarted — the client has
    the first half of the answer, and replaying it would duplicate
    output. So a failure is retried only while nothing has been yielded
    yet; after that the error is raised to the caller, which ends the
    stream.

    Args:
        query:  The user's natural-language question.
        chunks: Retrieved chunks, already ordered by similarity descending.

    Yields:
        Successive pieces of the answer text. May yield "" (never) — a
        chunk with no text contributes nothing and is skipped.

    Raises:
        RuntimeError: If GEMINI_API_KEY is not configured.
        Exception:    Propagated from the Gemini SDK on failure.
    """
    # No context is a complete, known answer, and it needs no model — so
    # it is answered before the API key is checked. Otherwise a user with
    # nothing indexed (or nothing matching) gets a 503 for a question
    # that was never going to reach Gemini.
    if not chunks:
        logger.info("No context chunks — returning fallback answer.")
        yield _NO_CONTEXT_ANSWER
        return

    _require_api_key()

    context_block = _build_context_block(chunks)
    prompt = _build_prompt(query, context_block)

    settings = get_settings()
    client = _get_gemini_client()
    model = settings.GEMINI_GENERATION_MODEL

    logger.info(
        "Streaming answer | model=%s chunks=%d query=%r", model, len(chunks), query[:80]
    )

    attempt = 0
    while True:
        emitted = False
        try:
            for part in client.models.generate_content_stream(
                model=model,
                contents=[
                    genai_types.Content(
                        role="user",
                        parts=[genai_types.Part(text=prompt)],
                    )
                ],
                config=_generation_config(),
            ):
                text = getattr(part, "text", None)
                if text:
                    emitted = True
                    yield text
            logger.info("Stream complete")
            return
        except Exception as exc:  # noqa: BLE001
            # If we already emitted text, we can't safely retry mid-stream.
            if emitted:
                logger.error("Stream failed after output began: %s", exc)
                raise

            # Quota errors carry the server's own backoff, so retrying
            # here would only burn more quota. Fail fast instead.
            if _is_quota_exceeded(exc):
                logger.error("Stream failed with quota error; not retrying: %s", exc)
                raise

            # No output yet and a transient error — apply retry logic.
            if not _is_transient_error(exc):
                logger.error("Stream failed with non-transient error: %s", exc)
                raise

            # Apply retry logic.
            if attempt >= _MAX_RETRIES:
                logger.error("Stream failed after %d retries: %s", attempt, exc)
                raise
            attempt += 1
            delay = _BASE_DELAY_S * (2 ** (attempt - 1))
            logger.warning(
                "Stream failed before any output (attempt %d/%d), retrying in %.1fs: %s",
                attempt,
                _MAX_RETRIES,
                delay,
                exc,
            )
            time.sleep(delay)
