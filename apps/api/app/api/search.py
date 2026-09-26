"""Search API router — POST /api/search (Part 14: hybrid retrieval)."""

from fastapi import APIRouter, HTTPException, status

from app.core.logging import logger
from app.core.security import CurrentUser
from app.rag.retrieval.search import (
    SearchOutcome,
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

    The response reports the mode that actually ran, so a hybrid search
    that had to fall back to vector-only is visible to the caller.
    """
    user_id = str(current_user.id)
    outcome: SearchOutcome
    results: list[SearchResultChunk]

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
        elif request.mode is SearchMode.vector:
            results = similarity_search(
                query=request.query,
                user_id=user_id,
                top_k=request.top_k,
                similarity_threshold=request.similarity_threshold,
                paper_ids=request.paper_ids,
            )
            outcome = SearchOutcome(results=results, mode=SearchMode.vector)
        else:
            outcome = hybrid_search(
                query=request.query,
                user_id=user_id,
                top_k=request.top_k,
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
    except RuntimeError as exc:
        # Gemini API key not configured
        logger.error("Search failed — configuration error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.error("Search failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Search failed. Please try again.",
        ) from exc

    logger.info(
        "Search complete | user=%s mode=%s results=%d",
        user_id,
        outcome.mode.value,
        len(results),
    )

    return SearchResponse(
        query=request.query,
        mode=outcome.mode,
        results=results,
        total_results=len(results),
    )
