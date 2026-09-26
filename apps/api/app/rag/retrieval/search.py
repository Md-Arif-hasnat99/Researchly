"""Semantic and keyword retrieval over ``paper_chunks``.

Two retrievers, one fusion step (Part 14, FR-14):

**Vector search** embeds the query with Gemini and calls the Postgres
function ``match_paper_chunks``, which wraps the pgvector ``<=>``
cosine-distance operator. Good at concepts, unreliable at names: two
embeddings for "BERT-base fine-tuning" and "ViT-L/16 fine-tuning" sit
close together, so a query for one returns the other almost as readily.

**Keyword search** calls ``search_paper_chunks_by_keyword``, a Postgres
full-text search over a generated tsvector column. It is exact about
proper nouns, model names, abbreviations, and dataset names, and it
needs no embedding call — so it keeps working when the Gemini key is
unavailable.

Query flow (hybrid)::

    User query string
         ↓
    embed_query()                              — Gemini RETRIEVAL_QUERY
         ├── match_paper_chunks()              — pgvector cosine, rank order
         └── search_paper_chunks_by_keyword()  — ts_rank, rank order
                    ↓
              rrf_fuse()                       — Reciprocal Rank Fusion
                    ↓
          [SearchResultChunk]                  — each tagged with matched_by

Fusion happens here rather than in SQL because RRF is rank-based: it
needs no score normalisation between cosine similarity and ts_rank, and
keeping it in Python makes the ranking itself unit-testable without a
database. Both Postgres functions independently enforce the ownership
gate, so neither half of the pipeline can reach another user's papers.
"""

import logging
from dataclasses import dataclass, field
from uuid import UUID

from app.core.supabase import get_supabase_client
from app.rag.embeddings.gemini import embed_query
from app.schemas.search import MatchSource, SearchMode, SearchResultChunk

logger = logging.getLogger("researchly")

# Reciprocal Rank Fusion damping constant. 60 is the value from the
# original Cormack et al. paper: large enough that the top few ranks
# are not overwhelmingly dominant, small enough that a chunk ranked
# well by both retrievers still beats one ranked well by a single
# retriever.
RRF_K = 60

# Each retriever is asked for more than the caller wants back, because a
# chunk that one retriever placed 15th may be the other retriever's top
# hit.  Fusing the full lists and truncating afterwards is the whole
# point of the candidate set in FR-14.
CANDIDATE_MULTIPLIER = 3

# Ceiling on per-retriever candidate depth, so a large top_k cannot turn
# one query into an unbounded pair of table scans.
MAX_CANDIDATES = 30


@dataclass
class SearchOutcome:
    """Results plus the retriever that actually produced them.

    ``mode`` is the *effective* mode. Hybrid search reports ``vector``
    when keyword search was unavailable, so a caller (and the API
    response) can tell the difference between "keyword found nothing"
    and "keyword never ran".
    """

    results: list[SearchResultChunk] = field(default_factory=list)
    mode: SearchMode = SearchMode.hybrid
    keyword_degraded: bool = False


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _candidate_depth(top_k: int) -> int:
    """Per-retriever candidate depth for a requested result count."""
    return min(MAX_CANDIDATES, max(top_k, top_k * CANDIDATE_MULTIPLIER))


def _row_to_chunk(row: dict, **extra) -> SearchResultChunk:
    """Map a Postgres function row onto a :class:`SearchResultChunk`.

    ``extra`` carries retriever-specific fields (``similarity_score`` /
    ``matched_by``) that the two functions return under different names.
    """
    return SearchResultChunk(
        chunk_id=row["chunk_id"],
        paper_id=row["paper_id"],
        paper_title=row["paper_title"],
        page_number=row["page_number"],
        section=row.get("section"),
        content=row["content"],
        **extra,
    )


def _log_query(query: str, user_id: str, top_k: int, mode: str, paper_ids) -> None:
    logger.info(
        "%s search | user=%s top_k=%d paper_ids=%s query=%r",
        mode.capitalize(),
        user_id,
        top_k,
        [str(p) for p in paper_ids] if paper_ids else "all",
        query[:80],
    )


# ---------------------------------------------------------------------------
# Vector retrieval
# ---------------------------------------------------------------------------


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
        descending.  Each result is tagged ``matched_by=['vector']``.

    Raises:
        RuntimeError: If the Gemini API key is not configured.
        Exception:    Propagated from the Gemini SDK or Supabase client.
    """
    _log_query(query, user_id, top_k, "vector", paper_ids)

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
        _row_to_chunk(
            row,
            similarity_score=round(float(row["similarity"]), 4),
            matched_by=["vector"],
        )
        for row in rows
    ]

    return results


# ---------------------------------------------------------------------------
# Keyword retrieval
# ---------------------------------------------------------------------------


def keyword_search(
    query: str,
    user_id: str,
    top_k: int = 8,
    paper_ids: list[UUID] | None = None,
) -> list[SearchResultChunk]:
    """Search paper_chunks for chunks lexically matching *query*.

    Unlike :func:`similarity_search` this embeds nothing, so it works
    without a configured Gemini API key.  Results carry no
    ``similarity_score`` — there is no vector comparison to report, and
    inventing one would misrepresent a lexical rank as a semantic score.

    Args:
        query:     Raw query text.  Quoted phrases, ``OR``, and a leading
                   ``-`` for negation are honoured (``websearch_to_tsquery``).
        user_id:   UUID string of the authenticated user; ownership gate.
        top_k:     Maximum number of results to return (1–20).
        paper_ids: Optional paper UUIDs to restrict the search to.

    Returns:
        List of :class:`SearchResultChunk` ordered by lexical relevance
        descending, each tagged ``matched_by=['keyword']``.
    """
    _log_query(query, user_id, top_k, "keyword", paper_ids)

    client = get_supabase_client()

    rpc_params: dict = {
        "query_text": query,
        "match_count": top_k,
        "filter_user_id": user_id,
    }
    if paper_ids:
        rpc_params["filter_paper_ids"] = [str(pid) for pid in paper_ids]
    else:
        rpc_params["filter_paper_ids"] = None

    response = client.rpc("search_paper_chunks_by_keyword", rpc_params).execute()

    rows: list[dict] = response.data or []
    logger.info("Full-text search returned %d candidate(s)", len(rows))

    return [
        _row_to_chunk(row, matched_by=["keyword"]) for row in rows
    ]


# ---------------------------------------------------------------------------
# Fusion
# ---------------------------------------------------------------------------


def rrf_fuse(
    vector_hits: list[SearchResultChunk],
    keyword_hits: list[SearchResultChunk],
    top_k: int = 8,
    k: int = RRF_K,
) -> list[SearchResultChunk]:
    """Fuse two ranked lists with Reciprocal Rank Fusion.

    Each chunk accumulates ``1 / (k + rank)`` for every retriever that
    returned it. A chunk both retrievers like therefore outranks a chunk
    that only one does, which is the behaviour FR-14 is after: the
    retrievers are individually weak exactly where the other is strong.

    Rank-based scoring means the two lists' incomparable score scales
    (cosine similarity, ``ts_rank``) never have to be normalised against
    each other, and no arbitrary weight has to be tuned to make them
    commensurable.

    Args:
        vector_hits:  Vector results, best first.
        keyword_hits: Keyword results, best first.
        top_k:        Maximum number of fused results to return.
        k:            RRF damping constant.

    Returns:
        Up to ``top_k`` fused results, best first, each carrying
        ``fusion_score`` and a ``matched_by`` list. ``similarity_score``
        is preserved from the vector side and stays ``None`` for
        keyword-only hits.
    """
    # chunk_id -> accumulator. dict preserves insertion order, which the
    # deterministic tie-break below makes irrelevant anyway.
    fused: dict[UUID, dict] = {}

    def absorb(hits: list[SearchResultChunk], source: MatchSource) -> None:
        # A retriever's own list should never repeat a chunk, but if one
        # did, counting it twice would inflate its fused score above any
        # genuinely agreed-upon result. Ranks stay tied to the list
        # position, so de-duplication does not shift the other ranks.
        seen: set[UUID] = set()
        for rank, hit in enumerate(hits, start=1):
            if hit.chunk_id in seen:
                continue
            seen.add(hit.chunk_id)
            entry = fused.get(hit.chunk_id)
            if entry is None:
                entry = {
                    "chunk": hit,
                    "score": 0.0,
                    "sources": [],
                }
                fused[hit.chunk_id] = entry
            entry["score"] += 1.0 / (k + rank)
            entry["sources"].append(source)

    absorb(vector_hits, "vector")
    absorb(keyword_hits, "keyword")

    # Ties are broken on (title, page) so that the same query issued
    # twice returns the same order.
    ordered = sorted(
        fused.values(),
        key=lambda e: (
            -e["score"],
            e["chunk"].paper_title,
            e["chunk"].page_number,
        ),
    )

    results: list[SearchResultChunk] = []
    for entry in ordered[:top_k]:
        base: SearchResultChunk = entry["chunk"]
        results.append(
            base.model_copy(
                update={
                    "matched_by": entry["sources"],
                    "fusion_score": round(entry["score"], 6),
                }
            )
        )

    return results


# ---------------------------------------------------------------------------
# Hybrid
# ---------------------------------------------------------------------------


def hybrid_search(
    query: str,
    user_id: str,
    top_k: int = 8,
    similarity_threshold: float = 0.65,
    paper_ids: list[UUID] | None = None,
) -> SearchOutcome:
    """Run both retrievers and fuse them (FR-14).

    Each retriever is asked for a deeper candidate list than the caller
    wants, then the fused list is truncated to ``top_k``.

    ``similarity_threshold`` applies to the vector side only. That is
    deliberate: the threshold exists to keep semantically distant chunks
    out of the candidate set, and a chunk that is lexically exact but
    cosinely distant is precisely the one keyword search exists to
    rescue.

    If keyword search fails — the migration may not have been applied to
    a given environment — the vector results are returned with
    ``mode=vector`` and ``keyword_degraded=True`` instead of failing the
    whole request. A degraded search is more useful than a 500, and the
    caller is told which retriever actually ran.
    """
    _log_query(query, user_id, top_k, "hybrid", paper_ids)
    depth = _candidate_depth(top_k)

    # A vector failure (missing API key, database down) is not something
    # to paper over — it propagates so the API can report it.
    vector_hits = similarity_search(
        query=query,
        user_id=user_id,
        top_k=depth,
        similarity_threshold=similarity_threshold,
        paper_ids=paper_ids,
    )

    degraded = False
    try:
        keyword_hits = keyword_search(
            query=query,
            user_id=user_id,
            top_k=depth,
            paper_ids=paper_ids,
        )
    except Exception as exc:  # noqa: BLE001
        degraded = True
        keyword_hits = []
        logger.warning(
            "Keyword search unavailable, falling back to vector-only: %s", exc
        )

    results = rrf_fuse(vector_hits, keyword_hits, top_k=top_k)
    logger.info(
        "Hybrid search | vector=%d keyword=%d fused=%d degraded=%s",
        len(vector_hits),
        len(keyword_hits),
        len(results),
        degraded,
    )

    return SearchOutcome(
        results=results,
        mode=SearchMode.vector if degraded else SearchMode.hybrid,
        keyword_degraded=degraded,
    )
