"""Search API router — POST /api/search."""

from fastapi import APIRouter, HTTPException, status

from app.core.logging import logger
from app.core.security import CurrentUser
from app.rag.retrieval.search import similarity_search
from app.schemas.search import SearchRequest, SearchResponse

router = APIRouter(prefix="/search", tags=["Search"])


@router.post("", response_model=SearchResponse)
async def search_papers(
    request: SearchRequest,
    current_user: CurrentUser,
) -> SearchResponse:
    """Semantic search across the user's paper library.

    Embeds the query with Gemini and performs a cosine-similarity search
    against all chunks belonging to the authenticated user (optionally
    restricted to specific paper IDs).

    Returns top-K chunks ordered by similarity score descending.
    """
    try:
        results = similarity_search(
            query=request.query,
            user_id=str(current_user.id),
            top_k=request.top_k,
            similarity_threshold=request.similarity_threshold,
            paper_ids=request.paper_ids,
        )
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

    return SearchResponse(
        query=request.query,
        results=results,
        total_results=len(results),
    )
