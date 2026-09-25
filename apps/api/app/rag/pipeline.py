"""Full RAG pipeline: retrieve → generate.

This module is the single entry point used by the chat API.
It combines:

1. :func:`similarity_search` — embed query + pgvector cosine search
2. :func:`generate_answer`   — grounded Gemini generation

and returns a :class:`RAGResult` containing the answer text,
the cited chunks, and the total number of chunks retrieved.
"""

import logging
from dataclasses import dataclass, field
from uuid import UUID

from app.rag.generation.gemini import GeneratedAnswer, generate_answer
from app.rag.retrieval.search import similarity_search
from app.schemas.search import SearchResultChunk

logger = logging.getLogger("researchly")


@dataclass
class RAGResult:
    """Complete result from one RAG pipeline invocation."""

    answer: str
    """The model's grounded answer text."""

    cited_chunks: list[SearchResultChunk] = field(default_factory=list)
    """Chunks used as context (ordered as [1], [2], …)."""

    retrieved_count: int = 0
    """Total chunks returned by similarity search before generation."""


def run_rag(
    query: str,
    user_id: str,
    top_k: int = 8,
    similarity_threshold: float = 0.65,
    paper_ids: list[UUID] | None = None,
) -> RAGResult:
    """Run the full RAG pipeline for a single user question.

    Args:
        query:                The user's question string.
        user_id:              UUID of the authenticated user.
        top_k:                Maximum chunks to retrieve and pass to Gemini.
        similarity_threshold: Minimum cosine similarity for retrieval.
        paper_ids:            Optional list of paper UUIDs to scope retrieval.

    Returns:
        :class:`RAGResult` with answer text and cited chunks.

    Raises:
        RuntimeError: If Gemini API key is not configured.
        Exception:    Propagated from Gemini SDK or Supabase on failure.
    """
    logger.info(
        "RAG pipeline start | user=%s query=%r top_k=%d paper_ids=%s",
        user_id,
        query[:80],
        top_k,
        [str(p) for p in paper_ids] if paper_ids else "all",
    )

    # Step 1: Retrieve relevant chunks
    chunks: list[SearchResultChunk] = similarity_search(
        query=query,
        user_id=user_id,
        top_k=top_k,
        similarity_threshold=similarity_threshold,
        paper_ids=paper_ids,
    )
    retrieved_count = len(chunks)
    logger.info("Retrieved %d chunks", retrieved_count)

    # Step 2: Generate grounded answer
    generated: GeneratedAnswer = generate_answer(query=query, chunks=chunks)

    logger.info("RAG pipeline complete — answer length=%d", len(generated.answer))

    return RAGResult(
        answer=generated.answer,
        cited_chunks=generated.cited_chunks,
        retrieved_count=retrieved_count,
    )
