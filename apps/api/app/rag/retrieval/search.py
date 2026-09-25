"""Semantic similarity search using pgvector.

Performs a nearest-neighbour search over ``paper_chunks.embedding``
using Supabase's ``rpc`` call to a Postgres function that wraps the
pgvector ``<=>`` cosine-distance operator.

The Postgres function ``match_paper_chunks`` must exist in the database
(see migration ``20260923000005_search_function.sql``).

Query flow::

    User query string
         ↓
    embed_query()           — Gemini RETRIEVAL_QUERY embedding
         ↓
    match_paper_chunks()    — Supabase RPC / pgvector cosine search
         ↓
    [SearchResultChunk]     — filtered by threshold, owned by user
"""

import logging
from uuid import UUID

from app.core.supabase import get_supabase_client
from app.rag.embeddings.gemini import embed_query
from app.schemas.search import SearchResultChunk

logger = logging.getLogger("researchly")


def similarity_search(
    query: str,
    user_id: str,
    top_k: int = 8,
    similarity_threshold: float = 0.65,
    paper_ids: list[UUID] | None = None,
) -> list[SearchResultChunk]:
    """Search paper_chunks for chunks semantically similar to *query*.

    Args:
        query:                Natural-language query string.
        user_id:              UUID string of the authenticated user; used to
                              enforce ownership — only the user's own papers
                              are searched.
        top_k:                Maximum number of results to return (1–20).
        similarity_threshold: Minimum cosine similarity score (0–1).  Chunks
                              below this value are discarded.
        paper_ids:            Optional list of paper UUIDs to restrict the
                              search to.  ``None`` searches all user papers.

    Returns:
        List of :class:`SearchResultChunk` ordered by similarity score
        descending.

    Raises:
        RuntimeError: If the Gemini API key is not configured.
        Exception:    Propagated from the Gemini SDK or Supabase client.
    """
    logger.info(
        "Similarity search | user=%s top_k=%d threshold=%.2f paper_ids=%s query=%r",
        user_id,
        top_k,
        similarity_threshold,
        [str(p) for p in paper_ids] if paper_ids else "all",
        query[:80],
    )

    # 1. Embed the query with RETRIEVAL_QUERY task type
    query_vector: list[float] = embed_query(query)

    # 2. Call the Postgres RPC function
    client = get_supabase_client()

    rpc_params: dict = {
        "query_embedding": query_vector,
        "match_count": top_k,
        "similarity_threshold": similarity_threshold,
        "filter_user_id": user_id,
    }
    if paper_ids:
        rpc_params["filter_paper_ids"] = [str(pid) for pid in paper_ids]
    else:
        rpc_params["filter_paper_ids"] = None

    response = client.rpc("match_paper_chunks", rpc_params).execute()

    rows: list[dict] = response.data or []
    logger.info("pgvector returned %d candidate(s)", len(rows))

    # 3. Map DB rows → schema objects
    results: list[SearchResultChunk] = [
        SearchResultChunk(
            chunk_id=row["chunk_id"],
            paper_id=row["paper_id"],
            paper_title=row["paper_title"],
            page_number=row["page_number"],
            section=row.get("section"),
            content=row["content"],
            similarity_score=round(float(row["similarity"]), 4),
        )
        for row in rows
    ]

    return results
