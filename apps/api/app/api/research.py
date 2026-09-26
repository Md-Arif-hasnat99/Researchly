"""Multi-paper research API router (Part 11).

Endpoints:
    POST /api/research/compare — structured cross-paper comparison matrix

Flow for POST /api/research/compare:
    1. Validate the caller's ownership of every requested paper.
    2. Retrieve per-paper context chunks (cross-paper retrieval).
    3. Generate a grounded comparison matrix.
    4. Return rows of cells, each traceable to a source page and chunk.
"""

from fastapi import APIRouter, HTTPException, status
from supabase import Client

from app.core.logging import logger
from app.core.security import CurrentUser
from app.core.supabase import get_supabase_client
from app.rag.generation.compare import PaperContext, generate_comparison
from app.rag.retrieval.search import similarity_search
from app.schemas.research import (
    DEFAULT_ASPECTS,
    CompareRequest,
    CompareResponse,
)

router = APIRouter(prefix="/research", tags=["Research"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fetch_owned_papers(client: Client, user_id: str, paper_ids: list[str]) -> dict:
    """Return {paper_id: row} for the caller's own ready papers.

    Raises 404 if any requested paper is missing, not owned, or not yet
    indexed — the response never reveals whether another user owns the ID.
    """
    try:
        result = (
            client.table("papers")
            .select("id, title, publication_year, status")
            .in_("id", paper_ids)
            .eq("user_id", user_id)
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Paper ownership lookup failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to verify paper ownership.",
        ) from exc

    rows = result.data or []
    if len(rows) != len(set(paper_ids)):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="One or more papers were not found in your library.",
        )

    not_ready = [r["title"] for r in rows if r.get("status") != "ready"]
    if not_ready:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "These papers are still being indexed and cannot be compared yet: "
                + ", ".join(not_ready)
            ),
        )

    return {str(r["id"]): r for r in rows}


def _build_contexts(
    user_id: str,
    papers: dict,
    per_paper_top_k: int,
    focus: str | None,
) -> list[PaperContext]:
    """Retrieve per-paper context and group it for matrix generation."""
    contexts: list[PaperContext] = []
    # The retrieval query steers which chunks each paper contributes. The
    # focus string (or a neutral default) is embedded per paper so every
    # paper is searched independently — this preserves source identity.
    query = focus or "dataset model method metrics results limitations"

    for paper_id, row in papers.items():
        try:
            chunks = similarity_search(
                query=query,
                user_id=user_id,
                top_k=per_paper_top_k,
                similarity_threshold=0.0,
                paper_ids=[paper_id],
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Retrieval failed for paper %s: %s", paper_id, exc)
            continue

        if not chunks:
            logger.info("No chunks retrieved for paper %s; excluding from matrix.", paper_id)
            continue

        contexts.append(
            PaperContext(
                paper_id=chunks[0].paper_id,
                paper_title=row["title"],
                publication_year=row.get("publication_year"),
                chunks=[
                    (c.page_number, c.content, c.chunk_id) for c in chunks
                ],
            )
        )

    return contexts


# ---------------------------------------------------------------------------
# POST /api/research/compare
# ---------------------------------------------------------------------------


@router.post("/compare", response_model=CompareResponse)
async def compare_papers(
    request: CompareRequest,
    current_user: CurrentUser,
) -> CompareResponse:
    """Compare two to six of the caller's papers across chosen aspects.

    Returns a matrix with one row per aspect and one cell per paper. Each
    cell carries the reported value (or ``not_reported``) plus the page and
    chunk it came from, so every factual claim stays traceable to a source.
    """
    user_id = str(current_user.id)
    client = get_supabase_client()
    paper_ids = [str(pid) for pid in request.paper_ids]

    # 1. Verify ownership and index state
    papers = _fetch_owned_papers(client, user_id, paper_ids)

    # 2. Cross-paper retrieval
    contexts = _build_contexts(
        user_id=user_id,
        papers=papers,
        per_paper_top_k=request.per_paper_top_k,
        focus=request.focus,
    )

    if len(contexts) < 2:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "At least two indexed papers are required for a comparison. "
                "Upload and process more papers, then try again."
            ),
        )

    # 3. Generate the matrix
    try:
        result = generate_comparison(
            contexts=contexts,
            aspects=request.aspects or DEFAULT_ASPECTS,
            focus=request.focus,
        )
    except RuntimeError as exc:
        logger.error("Comparison config error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.error("Comparison generation failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Comparison failed. Please try again.",
        ) from exc

    logger.info(
        "Comparison complete | user=%s papers=%d rows=%d citations=%d",
        user_id,
        len(result.papers),
        len(result.rows),
        result.citation_count,
    )

    return CompareResponse(
        papers=result.papers,
        rows=result.rows,
        summary=result.summary,
        citations=result.citations,
    )
