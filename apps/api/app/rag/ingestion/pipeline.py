"""Ingestion pipeline: extract → chunk → persist → update status.

This module is the single entry point for processing an uploaded PDF.

It is designed to be called both synchronously (in tests) and from a
background task spawned by the API layer.

The pipeline is **idempotent**: calling it multiple times on the same
paper produces the same result, and a transient failure does not destroy
previously embedded chunks.

Status transitions::

    uploaded  →  processing  →  ready
                              →  failed
"""

import logging
import time

from app.core.errors import safe_error_message
from app.core.supabase import get_supabase_client
from app.rag.embeddings.gemini import embed_texts
from app.rag.ingestion.chunker import chunk_pages
from app.rag.ingestion.extractor import extract_pages

logger = logging.getLogger("researchly")

# Maximum number of chunks inserted per DB call
_BATCH_SIZE = 100

# Retry configuration for the embedding step.
_MAX_RETRIES = 3
_BASE_DELAY_S = 1.0


def _paper_status(supabase, paper_id: str) -> str:
    """Return the current status of *paper_id*, or ``None`` if the row
    does not exist."""
    result = supabase.table("papers").select("status").eq("id", paper_id).execute()
    data = result.data
    return data[0]["status"] if data else None


def _update_paper_status(supabase, paper_id: str, new_status: str,
                         total_pages: int | None = None,
                         error_message: str | None = None) -> None:
    """Persist a status change on the ``papers`` row."""
    payload: dict = {"status": new_status}
    if total_pages is not None:
        payload["total_pages"] = total_pages
    if new_status == "ready":
        # Always clear any previous error message when the paper is ready.
        payload["error_message"] = None
    elif error_message is not None:
        payload["error_message"] = error_message[:2000]  # guard DB column length

    supabase.table("papers").update(payload).eq("id", paper_id).execute()
    logger.info("Paper %s → %s", paper_id, new_status)


def _insert_chunks_batch(chunks_payload: list[dict]) -> None:
    """Bulk-insert a list of chunk dicts into ``paper_chunks``."""
    supabase = get_supabase_client()
    for i in range(0, len(chunks_payload), _BATCH_SIZE):
        batch = chunks_payload[i : i + _BATCH_SIZE]
        supabase.table("paper_chunks").insert(batch).execute()
    logger.debug("Inserted %d chunks", len(chunks_payload))


def _embed_with_retry(texts_to_embed: list[str]) -> list[list[float]]:
    """Embed *texts_to_embed* with exponential-backoff retry.

    Retries only on ``RuntimeError`` (quota-exceeded, transient network
    failure).  After three attempts the original exception is raised.
    """
    delay = _BASE_DELAY_S
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            return embed_texts(texts_to_embed)
        except RuntimeError as exc:
            if attempt == _MAX_RETRIES:
                raise
            logger.warning(
                "Embedding attempt %d/%d failed: %s; retrying in %.1fs",
                attempt, _MAX_RETRIES, exc, delay,
            )
            time.sleep(delay)
            delay *= 2


def run_ingestion(paper_id: str, pdf_bytes: bytes) -> int:
    """Run the full ingestion pipeline for a single paper.

    Args:
        paper_id:  UUID string of the ``papers`` row.
        pdf_bytes: Raw PDF file bytes downloaded from Supabase Storage.

    Returns:
        Number of chunks stored.  Returns ``0`` if the paper has no
        extractable content or the pipeline is re-run on an already‑ready
        paper.

    Side-effects:
        - Updates ``papers.status`` to ``processing`` then ``ready``/``failed``.
        - Inserts rows into ``paper_chunks``.
        - Is **idempotent**: re-running on an already‑ready paper is a
          no-op that returns the stored chunk count.
    """
    supabase = get_supabase_client()

    # ----- idempotent guard -------------------------------------------------
    current = _paper_status(supabase, paper_id)
    if current == "ready":
        # Paper already fully processed; nothing to do.
        # Retrieve the chunk count once so we can return it.
        result = supabase.table("paper_chunks").select("id", count="exact").eq(
            "paper_id", paper_id
        ).execute()
        return result.count if result.count is not None else 0

    # ----- begin processing -------------------------------------------------
    _update_paper_status(supabase, paper_id, "processing")

    try:
        # 1. Extract text page-by-page
        pages = extract_pages(pdf_bytes)
        total_pages = len(pages)

        # 2. Chunk the extracted text
        chunks = chunk_pages(pages, paper_id)

        if not chunks:
            logger.warning("Paper %s produced no chunks (empty or image-only PDF)", paper_id)
            _update_paper_status(supabase, paper_id, "ready", total_pages=total_pages)
            return 0

        # 3. Generate embeddings for all chunks (retried on transient failure).
        texts_to_embed = [chunk.content for chunk in chunks]
        embeddings = _embed_with_retry(texts_to_embed)

        if len(embeddings) != len(chunks):
            # embed_texts already refuses a short batch, so reaching this
            # means the contract itself changed. Fail rather than write a
            # paper whose chunks and vectors no longer correspond.
            raise RuntimeError(
                f"Embedding count mismatch for paper {paper_id}: "
                f"{len(embeddings)} embeddings for {len(chunks)} chunks"
            )

        # 4. Replace the previous chunks now that the replacements are ready.
        supabase.table("paper_chunks").delete().eq("paper_id", paper_id).execute()
        logger.debug("Cleared existing chunks for paper %s", paper_id)

        # 5. Persist new chunks with their embeddings
        chunks_payload = [
            {
                "paper_id": chunk.paper_id,
                "content": chunk.content,
                "page_number": chunk.page_number,
                "section": chunk.section,
                "chunk_index": chunk.chunk_index,
                "embedding": embedding,
            }
            for chunk, embedding in zip(chunks, embeddings)
        ]
        _insert_chunks_batch(chunks_payload)

        # 4. Mark paper ready
        _update_paper_status(supabase, paper_id, "ready", total_pages=total_pages)
        logger.info(
            "Ingestion complete: paper=%s pages=%d chunks=%d",
            paper_id,
            total_pages,
            len(chunks),
        )
        return len(chunks)

    except Exception as exc:  # noqa: BLE001
        logger.error("Ingestion failed for paper %s: %s", paper_id, exc, exc_info=True)
        # Ensure the paper is never left in ``processing`` — a restart or
        # retry would otherwise spin forever.
        _update_paper_status(supabase, paper_id, "failed",
                             error_message=safe_error_message(
                                 exc, fallback="The file could not be processed as a PDF."
                             ))
        return 0
