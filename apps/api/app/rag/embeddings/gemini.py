"""Gemini embedding service.

Generates 768-dimensional text embeddings using Google's
``text-embedding-004`` model via the ``google-genai`` SDK.

Features:
- Batch processing (respects Gemini API batch limits)
- Exponential-backoff retry on transient failures
- Dimension validation (guards against API changes)
- Zero external state — pure functions, safe to call from threads
"""

import logging
import time
from collections.abc import Callable

import google.genai as genai
import google.genai.types as genai_types

from app.core.config import get_settings

logger = logging.getLogger("researchly")

# Gemini text-embedding-004 produces 768-dimensional vectors
EMBEDDING_DIM = 768

# Gemini API batch limit for embedContent (content items per request)
_BATCH_SIZE = 100

# Retry configuration
_MAX_RETRIES = 3
_BASE_DELAY_S = 1.0  # seconds; doubled on each retry


def _get_client() -> genai.Client:
    """Return a configured Gemini client."""
    settings = get_settings()
    return genai.Client(api_key=settings.GEMINI_API_KEY)


def _with_retry(fn: Callable, retries: int = _MAX_RETRIES, base_delay: float = _BASE_DELAY_S):
    """Call *fn()* with exponential-backoff retry on exception.

    Raises the last exception if all retries are exhausted.
    """
    delay = base_delay
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt < retries:
                logger.warning(
                    "Embedding attempt %d/%d failed (%s). Retrying in %.1fs…",
                    attempt + 1,
                    retries,
                    exc,
                    delay,
                )
                time.sleep(delay)
                delay *= 2
    raise last_exc  # type: ignore[misc]


def _validate_vector(vector: list[float], text_preview: str) -> list[float]:
    """Assert the vector has the expected dimension."""
    if len(vector) != EMBEDDING_DIM:
        raise ValueError(
            f"Expected {EMBEDDING_DIM}-dim vector, got {len(vector)} dims "
            f"for text starting with: {text_preview[:60]!r}"
        )
    return vector


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Generate embeddings for a list of text strings.

    Args:
        texts: Non-empty list of strings to embed.

    Returns:
        List of 768-dimensional float vectors, in the same order as *texts*.

    Raises:
        ValueError:   If a returned vector has the wrong dimension.
        RuntimeError: If the Gemini API key is not configured.
        Exception:    Propagated from the Gemini SDK after all retries fail.
    """
    settings = get_settings()
    if not settings.GEMINI_API_KEY:
        raise RuntimeError(
            "GEMINI_API_KEY is not configured. "
            "Set it in your .env file to enable embedding generation."
        )

    if not texts:
        return []

    client = _get_client()
    model = settings.GEMINI_EMBEDDING_MODEL
    all_vectors: list[list[float]] = []

    for batch_start in range(0, len(texts), _BATCH_SIZE):
        batch = texts[batch_start : batch_start + _BATCH_SIZE]

        def _embed_batch(b: list[str] = batch) -> list[list[float]]:
            response = client.models.embed_content(
                model=model,
                contents=b,
                config=genai_types.EmbedContentConfig(
                    task_type="RETRIEVAL_DOCUMENT",
                ),
            )
            return [list(emb.values) for emb in response.embeddings]

        vectors: list[list[float]] = _with_retry(_embed_batch)

        for vec, text in zip(vectors, batch):
            all_vectors.append(_validate_vector(vec, text))

        logger.debug(
            "Embedded batch %d–%d (%d vectors)",
            batch_start,
            batch_start + len(batch) - 1,
            len(batch),
        )

    logger.info("Generated %d embeddings via %s", len(all_vectors), model)
    return all_vectors


def embed_query(text: str) -> list[float]:
    """Embed a single query string for similarity search.

    Uses ``RETRIEVAL_QUERY`` task type so the vector is optimised for
    matching against ``RETRIEVAL_DOCUMENT`` vectors.

    Args:
        text: The query string.

    Returns:
        768-dimensional float vector.
    """
    settings = get_settings()
    if not settings.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not configured.")

    client = _get_client()
    model = settings.GEMINI_EMBEDDING_MODEL

    def _embed() -> list[float]:
        response = client.models.embed_content(
            model=model,
            contents=[text],
            config=genai_types.EmbedContentConfig(
                task_type="RETRIEVAL_QUERY",
            ),
        )
        return list(response.embeddings[0].values)

    vector: list[float] = _with_retry(_embed)
    return _validate_vector(vector, text)
