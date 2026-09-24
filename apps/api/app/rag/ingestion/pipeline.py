"""Ingestion pipeline: extract → chunk → persist → update status.

This module is the single entry point for processing an uploaded PDF.
It is designed to be called both synchronously (in tests) and from a
background task spawned by the API layer.

Status transitions::

    uploaded  →  processing  →  ready
                             →  failed
"""

import logging

from app.core.supabase import get_supabase_client
from app.rag.embeddings.gemini import embed_texts
from app.rag.ingestion.chunker import chunk_pages
from app.rag.ingestion.extractor import extract_pages

logger = logging.getLogger("researchly")

# Maximum number of chunks inserted per DB call
_BATCH_SIZE = 100


def _update_paper_status(
    paper_id: str,
    new_status: str,
    total_pages: int | None = None,
    error_message: str | None = None,
) -> None:
    """Persist a status change on the ``papers`` row."""
    client = get_supabase_client()
    payload: dict = {"status": new_status}
    if total_pages is not None:
        payload["total_pages"] = total_pages
    if new_status == "ready":
        # Always clear any previous error message when the paper is ready.
        payload["error_message"] = None
    elif error_message is not None:
        payload["error_message"] = error_message[:2000]  # guard DB column length

    client.table("papers").update(payload).eq("id", paper_id).execute()
    logger.info("Paper %s → %s", paper_id, new_status)


def _insert_chunks_batch(chunks_payload: list[dict]) -> None:
    """Bulk-insert a list of chunk dicts into ``paper_chunks``."""
    client = get_supabase_client()
    for i in range(0, len(chunks_payload), _BATCH_SIZE):
        batch = chunks_payload[i : i + _BATCH_SIZE]
        client.table("paper_chunks").insert(batch).execute()
    logger.debug("Inserted %d chunks", len(chunks_payload))


def run_ingestion(paper_id: str, pdf_bytes: bytes) -> int:
    """Run the full ingestion pipeline for a single paper.

    Args:
        paper_id:  UUID string of the ``papers`` row.
        pdf_bytes: Raw PDF file bytes downloaded from Supabase Storage.

    Returns:
        Number of chunks stored.

    Side-effects:
        - Updates ``papers.status`` to ``processing`` then ``ready``/``failed``.
        - Inserts rows into ``paper_chunks``.
    """
    _update_paper_status(paper_id, "processing")

    try:
        # 1. Extract text page-by-page
        pages = extract_pages(pdf_bytes)
        total_pages = len(pages)

        # 2. Chunk the extracted text
        chunks = chunk_pages(pages, paper_id)

        if not chunks:
            logger.warning("Paper %s produced no chunks (empty or image-only PDF)", paper_id)
            _update_paper_status(paper_id, "ready", total_pages=total_pages)
            return 0

        # 3. Delete any existing chunks so re-ingestion replaces prior results.
        get_supabase_client().table("paper_chunks").delete().eq(
            "paper_id", paper_id
        ).execute()
        logger.debug("Cleared existing chunks for paper %s", paper_id)

        # 4. Generate embeddings for all chunks
        texts_to_embed = [chunk.content for chunk in chunks]
        embeddings = []
        try:
            embeddings = embed_texts(texts_to_embed)
        except Exception as exc:
            logger.error("Failed to generate embeddings for paper %s: %s", paper_id, exc)
            raise RuntimeError(f"Embedding generation failed: {exc}") from exc

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
        _update_paper_status(paper_id, "ready", total_pages=total_pages)
        logger.info(
            "Ingestion complete: paper=%s pages=%d chunks=%d",
            paper_id,
            total_pages,
            len(chunks),
        )
        return len(chunks)

    except Exception as exc:  # noqa: BLE001
        logger.error("Ingestion failed for paper %s: %s", paper_id, exc, exc_info=True)
        _update_paper_status(paper_id, "failed", error_message=str(exc))
        return 0
