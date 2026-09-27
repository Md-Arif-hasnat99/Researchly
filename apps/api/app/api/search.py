"""Search API router — POST /api/search (Part 14 hybrid, Part 15 rerank)."""

from fastapi import APIRouter, HTTPException, status

from app.core.config import get_settings
from app.core.logging import logger
from app.core.security import CurrentUser
from app.rag.retrieval.rerank import rerank_chunks
from app.rag.retrieval.search import (
    SearchOutcome,
    candidate_depth,
    hybrid_search,
    keyword_search,
    similarity_search,
)
from app.schemas.search import (
    SearchMode,
    SearchRequest,
    SearchResponse,
    SearchResultChunk,
)

router = APIRouter(prefix="/search", tags=["Search"])


@router.post("", response_model=SearchResponse)
async def search_papers(
    request: SearchRequest,
    current_user: CurrentUser,
) -> SearchResponse:
    """Search the user's paper library.

    Dispatches to the retriever named by ``mode``:

    * ``hybrid`` (default) — vector + keyword results fused by Reciprocal
      Rank Fusion.  Recovers exact names, abbreviations, and dataset
      identifiers that vector search alone tends to blur.
    * ``vector`` — cosine similarity only.
    * ``keyword`` — full-text only; requires no embedding call, so it
      still works with no Gemini API key configured.

    When reranking is enabled (FR-15) the full candidate set is re-scored
    for genuine relevance before the list is cut down to ``top_k``,
    instead of simply keeping the retrievers' first ``top_k``.

    The response reports the mode that actually ran, so a hybrid search
    that had to fall back to vector-only is visible to the caller, and
    ``reranked`` is only true when a reranker really did the ordering.
    """
    user_id = str(current_user.id)
    settings = get_settings()
    outcome: SearchOutcome
    results: list[SearchResultChunk]

    # Reranking is skipped in keyword mode: lexical ranking is already
    # exact, so there is little for a relevance model to add and it would
    # only add latency and a dependency on the Gemini key.
    rerank_requested = (
        request.rerank
        if request.rerank is not None
        else settings.RERANK_SEARCH_DEFAULT
    )
    if rerank_requested and request.mode is SearchMode.keyword:
        logger.info("Rerank ignored: keyword mode ranks lexically already.")
        rerank_requested = False

    try:
        if request.mode is SearchMode.keyword:
            # No embedding call, so this path cannot raise the missing
            # API key RuntimeError the other two modes can.
            results = keyword_search(
                query=request.query,
                user_id=user_id,
                top_k=request.top_k,
                paper_ids=request.paper_ids,
            )
            outcome = SearchOutcome(results=results, mode=SearchMode.keyword)
        else:
            # With reranking on, retrieve deeper than the caller asked for
            # so the reranker has a real choice; without it, the
            # retrievers' own top_k is the answer. Fetching top_k first
            # and reranking afterwards would leave the reranker nothing to
            # choose between.
            fetch_depth = (
                candidate_depth(request.top_k) if rerank_requested else request.top_k
            )
            if request.mode is SearchMode.vector:
                results = similarity_search(
                    query=request.query,
                    user_id=user_id,
                    top_k=fetch_depth,
                    similarity_threshold=request.similarity_threshold,
                    paper_ids=request.paper_ids,
                )
                outcome = SearchOutcome(results=results, mode=SearchMode.vector)
            else:
                outcome = hybrid_search(
                    query=request.query,
                    user_id=user_id,
                    top_k=fetch_depth,
                    similarity_threshold=request.similarity_threshold,
                    paper_ids=request.paper_ids,
                )
                if outcome.keyword_degraded:
                    logger.warning(
                        "Hybrid search degraded to vector-only | user=%s query=%r",
                        user_id,
                        request.query[:80],
                    )
                results = outcome.results

        # FR-15: rerank the full candidate set, then truncate to top_k.
        reranked = False
        if rerank_requested:
            rerank_result = rerank_chunks(
                query=request.query,
                candidates=results,
                top_k=request.top_k,
            )
            results = rerank_result.chunks
            reranked = rerank_result.reranked
    except RuntimeError as exc:
        # Usually "GEMINI_API_KEY is not configured" — an internal config
        # detail. Log the cause; give the user a plain availability
        # message.
        logger.error("Search failed — configuration error: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Search is temporarily unavailable. Please try again shortly.",
        ) from exc
    except Exception as exc:
        logger.error("Search failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Search failed. Please try again.",
        ) from exc

    logger.info(
        "Search complete | user=%s mode=%s results=%d reranked=%s",
        user_id,
        outcome.mode.value,
        len(results),
        reranked,
    )

    return SearchResponse(
        query=request.query,
        mode=outcome.mode,
        results=results,
        total_results=len(results),
        reranked=reranked,
    )
