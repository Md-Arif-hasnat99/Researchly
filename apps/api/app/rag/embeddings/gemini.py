"""Gemini embedding service.

Generates 768-dimensional text embeddings using Google's
``text-embedding-004`` model via the ``google-genai`` SDK.

Features:
- Batched embedding (respects Gemini API batch limits)
- Batches embedded concurrently, results returned in input order
- Exponential-backoff retry on transient failures
- Dimension and cardinality validation (guards against API changes)
- Zero external state — pure functions, safe to call from threads
"""

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

import google.genai as genai
import google.genai.types as genai_types

from app.core.config import get_settings
from app.core.retry import with_retry

logger = logging.getLogger("researchly")

# Gemini text-embedding-004 produces 768-dimensional vectors
EMBEDDING_DIM = 768

# Gemini API batch limit for embedContent (content items per request)
_BATCH_SIZE = 100

# How many batches may be in flight at once. The requests are independent,
# so throughput scales with this, but each one holds a connection to Gemini
# and contributes to the per-project rate limit, so it stays modest rather
# than unbounded.
_MAX_CONCURRENT_BATCHES = 4

# Retry configuration (see app.core.retry for what counts as transient)
_MAX_RETRIES = 3
_BASE_DELAY_S = 1.0  # seconds; doubled on each retry


def _get_client() -> genai.Client:
    """Return a configured Gemini client."""
    settings = get_settings()
    return genai.Client(api_key=settings.GEMINI_API_KEY)


def _with_retry(fn: Callable, retries: int = _MAX_RETRIES, base_delay: float = _BASE_DELAY_S):
    """Call *fn()* with exponential-backoff retry on transient failures.

    Raises the last exception if all retries are exhausted, or
    immediately when the failure cannot succeed on a retry (a bad API
    key, a rejected payload).
    """
    return with_retry(
        fn, retries=retries, base_delay=base_delay, label="embedding request"
    )


def _validate_vector(vector: list[float]) -> list[float]:
    """Assert the vector has the expected dimension.

    The offending text is neither needed nor appropriate to echo: this
    error surfaces as a 422 body, and repeating a preview of the caller's
    text in a response helps nobody.
    """
    if len(vector) != EMBEDDING_DIM:
        raise ValueError(
            f"Embedding model returned {len(vector)} dimensions, expected {EMBEDDING_DIM}. "
            "The embedding model may have changed; check the server configuration."
        )
    return vector


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Generate embeddings for a list of text strings.

    Batches are embedded **concurrently** (bounded by
    ``_MAX_CONCURRENT_BATCHES``) rather than one after another. A paper
    of 500 chunks is 5 requests to Gemini, and the requests are
    independent, so serialising them multiplied ingestion time by the
    batch count for no benefit. Results are reassembled in the caller's
    original order.

    Args:
        texts: Non-empty list of strings to embed.

    Returns:
        List of 768-dimensional float vectors, in the same order and
        with the same length as *texts*.

    Raises:
        ValueError:   If a returned vector has the wrong dimension, or
                      the API returns a different number of vectors than
                      inputs (which would otherwise misalign every
                      downstream chunk-to-vector pairing).
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
    batches = [texts[i : i + _BATCH_SIZE] for i in range(0, len(texts), _BATCH_SIZE)]

    def _embed_batch(batch: list[str]) -> list[list[float]]:
        def _call() -> list[list[float]]:
            response = client.models.embed_content(
                model=model,
                contents=batch,
                config=genai_types.EmbedContentConfig(
                    task_type="RETRIEVAL_DOCUMENT",
                    # Pinned rather than assumed: the model supports
                    # several output widths, and paper_chunks.embedding
                    # is a vector(768) column. Asking for 768 explicitly
                    # means a model default change surfaces as a
                    # dimension error we can report, instead of a
                    # Postgres insert failure at the end of ingestion.
                    output_dimensionality=EMBEDDING_DIM,
                ),
            )
            return [list(emb.values) for emb in response.embeddings]

        vectors = _with_retry(_call)

        # A short response means the vectors no longer line up with the
        # inputs. Callers zip them positionally, so this must fail loudly
        # rather than silently associate a chunk with another chunk's
        # vector — or, worse, truncate the paper's chunks in silence.
        if len(vectors) != len(batch):
            raise ValueError(
                f"Gemini returned {len(vectors)} embeddings for "
                f"{len(batch)} inputs; refusing to misalign them."
            )
        return [_validate_vector(vec) for vec in vectors]

    with ThreadPoolExecutor(max_workers=min(_MAX_CONCURRENT_BATCHES, len(batches))) as pool:
        # map preserves order, so the result is independent of the order
        # in which the batches actually complete.
        per_batch = list(pool.map(_embed_batch, batches))

    all_vectors: list[list[float]] = [vec for batch_vectors in per_batch for vec in batch_vectors]
    logger.info(
        "Generated %d embeddings in %d batch(es) via %s",
        len(all_vectors),
        len(batches),
        model,
    )
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
                # Must match the document side exactly, or a query vector
                # and the stored chunk vectors are not comparable.
                output_dimensionality=EMBEDDING_DIM,
            ),
        )
        return list(response.embeddings[0].values)

    vector: list[float] = _with_retry(_embed)
    return _validate_vector(vector)
