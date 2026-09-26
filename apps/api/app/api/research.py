"""Multi-paper research API router (Part 11, Part 12, Part 13).

Endpoints:
    POST /api/research/compare           — structured cross-paper comparison matrix
    POST /api/research/literature-review — structured multi-section synthesis
    POST /api/research/gaps              — recurring research gap extraction

Shared flow for all endpoints:
    1. Validate the caller's ownership of every requested paper.
    2. Retrieve per-paper context chunks (cross-paper retrieval).
    3. Generate a grounded, schema-constrained result.
    4. Return content where every factual claim is traceable to a source
       page and chunk.
"""

from fastapi import APIRouter, HTTPException, status
from supabase import Client

from app.core.logging import logger
from app.core.security import CurrentUser
from app.core.supabase import get_supabase_client
from app.rag.generation.compare import PaperContext, generate_comparison
from app.rag.generation.gaps import identify_research_gaps
from app.rag.generation.literature_review import generate_literature_review
from app.rag.retrieval.search import similarity_search
from app.schemas.research import (
    DEFAULT_ASPECTS,
    CompareRequest,
    CompareResponse,
    GapRequest,
    GapResponse,
    LiteratureReviewRequest,
    LiteratureReviewResponse,
)

router = APIRouter(prefix="/research", tags=["Research"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fetch_owned_papers(
    client: Client,
    user_id: str,
    paper_ids: list[str],
    action: str = "compared",
) -> dict:
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
                f"These papers are still being indexed and cannot be {action} yet: "
                + ", ".join(not_ready)
            ),
        )

    return {str(r["id"]): r for r in rows}


def _build_contexts(
    user_id: str,
    papers: dict,
    per_paper_top_k: int,
    focus: str | None,
    default_query: str,
) -> list[PaperContext]:
    """Retrieve per-paper context and group it for cross-paper generation.

    Each paper is searched **independently** so source identity is preserved
    through synthesis: a claim in the output can always be traced back to
    exactly one paper's chunks.
    """
    contexts: list[PaperContext] = []
    # The retrieval query steers which chunks each paper contributes. The
    # focus string (or a caller-supplied default) is embedded per paper.
    query = focus or default_query

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
            logger.info("No chunks retrieved for paper %s; excluding.", paper_id)
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


# Neutral retrieval probes used when the caller supplies no focus. Each
# endpoint embeds its own so the retrieved chunks match the content the
# generator is about to ask for.
_COMPARISON_QUERY = "dataset model method metrics results limitations"
_REVIEW_QUERY = (
    "introduction background approach methodology dataset evaluation "
    "results limitations future work"
)
# Gap analysis searches specifically for the language of unresolved problems:
# stated limitations, caveats, open questions, and future-work sections.
_GAP_QUERY = (
    "limitations future work open questions challenges weaknesses "
    "evaluation threats unresolved problems"
)


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
        default_query=_COMPARISON_QUERY,
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


# ---------------------------------------------------------------------------
# POST /api/research/literature-review
# ---------------------------------------------------------------------------


@router.post("/literature-review", response_model=LiteratureReviewResponse)
async def generate_review(
    request: LiteratureReviewRequest,
    current_user: CurrentUser,
) -> LiteratureReviewResponse:
    """Generate a structured literature review across the caller's papers.

    Returns ordered sections following the FR-12 structure. Each section
    carries the sources it drew on, and a section the context could not
    support is explicitly flagged rather than padded with invented prose.
    """
    user_id = str(current_user.id)
    client = get_supabase_client()
    paper_ids = [str(pid) for pid in request.paper_ids]

    # 1. Verify ownership and index state
    papers = _fetch_owned_papers(client, user_id, paper_ids, action="synthesized")

    # 2. Cross-paper retrieval
    contexts = _build_contexts(
        user_id=user_id,
        papers=papers,
        per_paper_top_k=request.per_paper_top_k,
        focus=request.focus,
        default_query=_REVIEW_QUERY,
    )

    if len(contexts) < 2:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "At least two indexed papers are required for a literature review. "
                "Upload and process more papers, then try again."
            ),
        )

    # 3. Generate the review
    try:
        result = generate_literature_review(
            contexts=contexts,
            sections=request.sections,
            title=request.title,
            focus=request.focus,
        )
    except RuntimeError as exc:
        logger.error("Literature review config error: %s", exc)
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
        logger.error("Literature review generation failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Literature review generation failed. Please try again.",
        ) from exc

    grounded = sum(1 for s in result.sections if not s.insufficient_context)
    logger.info(
        "Literature review complete | user=%s papers=%d sections=%d grounded=%d citations=%d",
        user_id,
        len(result.papers),
        len(result.sections),
        grounded,
        result.citation_count,
    )

    return result.to_response()


# ---------------------------------------------------------------------------
# POST /api/research/gaps
# ---------------------------------------------------------------------------


@router.post("/gaps", response_model=GapResponse)
async def find_gaps(
    request: GapRequest,
    current_user: CurrentUser,
) -> GapResponse:
    """Identify recurring research gaps across the caller's papers.

    Returns gaps clustered by the FR-13 categories, most recurring first.
    Each gap separates the evidence stated by the papers from the AI's
    interpretation, and carries server-resolved source citations.
    """
    user_id = str(current_user.id)
    client = get_supabase_client()
    paper_ids = [str(pid) for pid in request.paper_ids]

    # 1. Verify ownership and index state
    papers = _fetch_owned_papers(client, user_id, paper_ids, action="analysed")

    # 2. Cross-paper retrieval, steered toward limitations and future work
    contexts = _build_contexts(
        user_id=user_id,
        papers=papers,
        per_paper_top_k=request.per_paper_top_k,
        focus=request.focus,
        default_query=_GAP_QUERY,
    )

    if not contexts:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "No indexed content was found for the selected papers. "
                "Wait for processing to finish, then try again."
            ),
        )

    # 3. Extract gaps
    try:
        result = identify_research_gaps(
            contexts=contexts,
            categories=request.categories,
            focus=request.focus,
        )
    except RuntimeError as exc:
        logger.error("Gap analysis config error: %s", exc)
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
        logger.error("Gap analysis failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Research gap analysis failed. Please try again.",
        ) from exc

    logger.info(
        "Gap analysis complete | user=%s papers=%d gaps=%d categories=%d citations=%d",
        user_id,
        len(result.papers),
        result.gap_count,
        len(result.clusters),
        result.citation_count,
    )

    return result.to_response()
