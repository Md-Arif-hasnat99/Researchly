"""Running an evaluation (FR-16).

Orchestrates one pass over the dataset: retrieve, optionally generate an
answer, score retrieval deterministically, and judge generation quality.
It is a plain function over an injected set of collaborators so tests
can drive it with fakes and no database, embeddings, or API key.

One behaviour is worth stating outright, because it is the kind of thing
that quietly inflates a score: **cases whose gold papers are not in the
library are skipped, not scored as failures.** Retrieval *cannot* find a
document the library does not contain, so counting those as misses would
measure the dataset's fit to the library rather than the system's
quality. The skipped ids are recorded in the report's manifest.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from app.core.config import get_settings
from app.evaluation.dataset import EvalDataset, resolve_gold
from app.evaluation.judge import GENERATION_METRICS, Judgement, judge_metric
from app.evaluation.metrics import aggregate, score_case
from app.evaluation.report import (
    CaseResult,
    EvalReport,
    GenerationAggregate,
    aggregate_generation,
)
from app.rag.generation.gemini import generate_answer
from app.rag.retrieval.search import (
    hybrid_search,
    keyword_search,
    similarity_search,
)
from app.schemas.search import SearchMode, SearchResultChunk

logger = logging.getLogger("researchly")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class EvalConfig:
    """Retrieval settings under evaluation.

    Defaults mirror the API's own defaults, so a run with no flags
    measures the system as a user actually meets it. In particular
    ``rerank`` defaults on, because search reranking is on by default in
    the shipped API (``RERANK_SEARCH_DEFAULT``): defaulting it off here
    would quietly measure a configuration nobody deploys and invite a
    "reranking made retrieval worse" reading of an A/B nobody ran. The
    no-rerank arm is opt-in with ``--no-rerank``.
    """

    k: int = 5
    mode: str = "hybrid"
    rerank: bool = True
    similarity_threshold: float = 0.65
    generate: bool = True
    judge_metrics: tuple[str, ...] = GENERATION_METRICS

    def as_dict(self) -> dict:
        return {
            "k": self.k,
            "mode": self.mode,
            "rerank": self.rerank,
            "similarity_threshold": self.similarity_threshold,
            "generate": self.generate,
            "judge_metrics": list(self.judge_metrics),
        }

    def resolved_mode(self) -> SearchMode:
        return SearchMode(self.mode)


# ---------------------------------------------------------------------------
# Library access
# ---------------------------------------------------------------------------


def fetch_library_titles(user_id: str) -> dict[str, UUID]:
    """Map every paper title in the user's library to its UUID.

    Raises:
        Exception: propagates from Supabase. A run that cannot see the
            library cannot resolve gold labels, and reporting "0 cases"
            would be indistinguishable from a real, terrible result.
    """
    from app.core.supabase import get_supabase_client

    client = get_supabase_client()
    response = (
        client.table("papers")
        .select("id, title")
        .eq("user_id", user_id)
        .execute()
    )
    return {row["title"]: UUID(row["id"]) for row in (response.data or [])}


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------


def retrieve(
    question: str,
    user_id: str,
    config: EvalConfig,
) -> list[SearchResultChunk]:
    """Run retrieval for one question at the configured cutoff.

    When reranking is on, retrieval over-fetches and the reranker picks
    the top ``k`` — the same path the API takes, so the measured
    configuration is the shipped configuration.
    """
    from app.rag.retrieval.rerank import rerank_chunks
    from app.rag.retrieval.search import candidate_depth

    if config.mode == SearchMode.keyword.value:
        return keyword_search(query=question, user_id=user_id, top_k=config.k)

    fetch_depth = candidate_depth(config.k) if config.rerank else config.k
    mode = config.resolved_mode()

    if mode is SearchMode.vector:
        chunks = similarity_search(
            query=question,
            user_id=user_id,
            top_k=fetch_depth,
            similarity_threshold=config.similarity_threshold,
        )
    else:
        chunks = hybrid_search(
            query=question,
            user_id=user_id,
            top_k=fetch_depth,
            similarity_threshold=config.similarity_threshold,
        ).results

    if config.rerank:
        chunks = rerank_chunks(query=question, candidates=chunks, top_k=config.k).chunks
    return chunks


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def _models_under_test(config: EvalConfig) -> dict[str, str]:
    """Which models this run actually involved.

    Recorded so a later comparison can refuse to difference two runs that
    used different models. A retrieval-only run involves no model and
    records none -- an empty manifest is the honest answer there, not a
    missing one.
    """
    if not config.generate:
        return {}
    settings = get_settings()
    models = {"generator": settings.GEMINI_GENERATION_MODEL}
    if config.judge_metrics:
        models["judge"] = settings.GEMINI_GENERATION_MODEL
    return models


def run_evaluation(
    dataset: EvalDataset,
    user_id: str,
    config: EvalConfig | None = None,
    retrieve_fn: Callable[[str, str, EvalConfig], list[SearchResultChunk]] | None = None,
    generate_fn: Callable[[str, list[SearchResultChunk]], object] | None = None,
    judge_fn: Callable[..., object] | None = None,
    library_titles: dict[str, UUID] | None = None,
) -> EvalReport:
    """Run every resolvable case and build a report.

    Args:
        dataset:        Loaded dataset. Gold labels are resolved in place.
        user_id:        Whose library to evaluate against.
        config:         Retrieval/generation settings. Defaults to the API's.
        retrieve_fn:    Override for retrieval, for tests.
        generate_fn:    Override for generation, for tests.
        judge_fn:       Override for the judge, for tests.
        library_titles: Pre-fetched title → id map. Fetched when omitted.

    Returns:
        :class:`EvalReport` with per-case results and aggregate metrics.
    """
    config = config or EvalConfig()
    retrieve_fn = retrieve_fn or retrieve
    generate_fn = generate_fn or generate_answer
    judge_fn = judge_fn or judge_metric

    if library_titles is None:
        library_titles = fetch_library_titles(user_id)
    resolve_gold(dataset, library_titles)

    unresolved = [case.id for case in dataset.unresolved_cases()]
    if unresolved:
        logger.warning(
            "Skipping %d case(s) whose gold papers are not in the library: %s",
            len(unresolved),
            ", ".join(unresolved),
        )

    results: list[CaseResult] = []
    for case in dataset.resolved_cases():
        logger.info("Evaluating case %s: %r", case.id, case.question[:80])
        result = _run_case(case, user_id, config, retrieve_fn, generate_fn, judge_fn)
        results.append(result)

    retrieval_scores = [r.retrieval for r in results if r.retrieval]
    report = EvalReport(
        dataset=dataset,
        config=config.as_dict(),
        retrieval=aggregate(retrieval_scores, config.k),
        generation=(
            aggregate_generation(results) if config.generate else GenerationAggregate()
        ),
        results=results,
        unresolved_case_ids=unresolved,
        models=_models_under_test(config),
    )
    logger.info(
        "Evaluation complete | cases=%d unresolved=%d %s",
        len(results),
        len(unresolved),
        report.retrieval.as_dict() if report.retrieval else "",
    )
    return report


def _run_case(
    case,
    user_id: str,
    config: EvalConfig,
    retrieve_fn: Callable[[str, str, EvalConfig], list[SearchResultChunk]],
    generate_fn: Callable[[str, list[SearchResultChunk]], object],
    judge_fn: Callable[..., object],
) -> CaseResult:
    """Run one case, keeping failures inside the report."""
    result = CaseResult(
        case_id=case.id,
        question=case.question,
        tags=list(case.tags),
        expected_characteristics=list(case.expected_answer_characteristics),
    )

    try:
        result.retrieved = retrieve_fn(case.question, user_id, config)
    except Exception as exc:  # noqa: BLE001
        # A case that cannot be retrieved is reported as an error case
        # rather than aborting the run: a single embedding timeout should
        # not cost the other 19 cases their scores.
        logger.warning("Retrieval failed for case %s: %s", case.id, exc)
        result.error = f"retrieval failed: {exc}"
        return result

    result.retrieval = score_case(case, result.retrieved, config.k)

    if not config.generate:
        return result

    try:
        generated = generate_fn(case.question, result.retrieved)
        result.answer = generated.answer
        result.citations = [str(c.chunk_id) for c in generated.cited_chunks]
    except Exception as exc:  # noqa: BLE001
        logger.warning("Generation failed for case %s: %s", case.id, exc)
        result.error = f"generation failed: {exc}"
        return result

    # Every configured metric is judged whenever there is an answer to
    # grade. A case with no recorded `expected_answer_characteristics` is
    # still measurable: faithfulness, context relevance and citation
    # accuracy are all judged from the excerpts and the answer alone, and
    # gating them on a field the dataset author may simply not have filled
    # in would silently drop cases from the generation metrics and make an
    # authoring gap look like a quality result.
    for metric in config.judge_metrics:
        try:
            result.judgements.append(
                judge_fn(metric, case.question, result.answer, result.retrieved)
            )
        except Exception as exc:  # noqa: BLE001
            # judge_metric already returns unscored judgements for its own
            # failures, but an injected judge (tests, alternative backends)
            # may raise instead. One metric must not cost the run its
            # remaining cases, matching the retrieval and generation
            # handling above.
            logger.warning("Judging failed for case %s / %s: %s", case.id, metric, exc)
            result.judgements.append(
                Judgement(metric=metric, score=None, error=f"judge raised: {exc}")
            )

    return result
