"""Retrieval quality metrics (FR-16).

These are the numbers that make claims about the retrieval stack
falsifiable. They are pure functions over retrieved chunks: no database,
no model, no network. That is deliberate — a metric that can change
because an embedding service was slow is not a metric, and FR-15's
reranker in particular deserves numbers that cannot drift with the
weather.

Definitions used here, stated explicitly because "recall@k" means
slightly different things in different papers:

**Relevant** means a retrieved chunk whose ``(paper_id, page_number)``
pair is in the case's gold set. The page is part of the label on
purpose: a chunk from the right paper on the wrong page does not contain
the answer, and counting it would let a retriever look good by dumping
every page of one paper.

**Hit Rate@K** — fraction of cases where at least one relevant chunk
appears in the top K. Answers "does the system find the answer at all?"

**Recall@K** — per case, ``relevant retrieved in top K / total gold``.
Averaged over cases. A case with two acceptable pages needs both to score
1.0, which is what makes this sensitive to a retriever that only ever
returns one page per paper.

**Precision@K** — per case, ``relevant retrieved in top K / K``. The
denominator is K, not the number of results returned, so returning three
chunks to fill a K of 10 scores 0.3 rather than a perfect 1.0. Precision
is only meaningful as a penalty on padding.

**MRR@K** — per case, ``1 / rank`` of the first relevant chunk within
the top K, else 0. Answers "how far down did the user have to look?"

Every metric here is a macro average over cases (each case counts once),
never a micro average over chunks, because a case that returns 30 chunks
would otherwise dominate a case that returns 3.
"""

import logging
from dataclasses import dataclass, field

from app.evaluation.dataset import EvalCase, GoldRef
from app.schemas.search import SearchResultChunk

logger = logging.getLogger("researchly")


# ---------------------------------------------------------------------------
# Relevance
# ---------------------------------------------------------------------------


def _ref(chunk: SearchResultChunk) -> GoldRef:
    """The (paper, page) pair a chunk would be judged on."""
    return GoldRef(paper_id=chunk.paper_id, page_number=chunk.page_number)


def is_relevant(chunk: SearchResultChunk, gold: set[GoldRef]) -> bool:
    """Whether *chunk* matches any gold reference for its case."""
    return _ref(chunk) in gold


def relevant_ranks(
    retrieved: list[SearchResultChunk],
    gold: set[GoldRef],
    k: int,
) -> list[int]:
    """1-based ranks (within the top K) of relevant chunks, in result order.

    Duplicate results are *not* collapsed: a retriever that returns the
    same page three times has not found three relevant things, and
    counting each copy would inflate recall and precision.
    """
    return [
        position
        for position, chunk in enumerate(retrieved[:k], start=1)
        if is_relevant(chunk, gold)
    ]


# ---------------------------------------------------------------------------
# Per-case scores
# ---------------------------------------------------------------------------


@dataclass
class CaseScore:
    """Scores for a single evaluation case at one cutoff K."""

    case_id: str
    k: int
    retrieved: int
    """How many chunks the retriever returned, before the K cutoff."""

    relevant_retrieved: int
    """How many of the top K were relevant, duplicates collapsed."""

    gold_total: int
    """How many gold references the case defines."""

    hit: bool
    recall: float
    precision: float
    reciprocal_rank: float

    first_relevant_rank: int | None = None
    """1-based rank of the first relevant chunk in the top K, else None."""

    detail: list[str] = field(default_factory=list)
    """Human-readable provenance, e.g. "rank 1 → p7 (expected p9)".

    Included in the report so a surprising number can be traced to the
    exact result that caused it, rather than requiring a re-run.
    """


def score_case(
    case: EvalCase,
    retrieved: list[SearchResultChunk],
    k: int,
) -> CaseScore:
    """Score one case: did retrieval find the gold pages in the top K?"""
    gold = case.gold_refs()
    ranks = relevant_ranks(retrieved, gold, k)

    # Collapse duplicate pages: a repeated hit is one piece of evidence.
    matched = {_ref(retrieved[rank - 1]) for rank in ranks}
    relevant_retrieved = len(matched)
    gold_total = len(gold)

    hit = bool(ranks)
    recall = (relevant_retrieved / gold_total) if gold_total else 0.0
    precision = (relevant_retrieved / k) if k else 0.0
    reciprocal_rank = (1.0 / ranks[0]) if ranks else 0.0

    detail: list[str] = []
    for rank in ranks:
        chunk = retrieved[rank - 1]
        detail.append(f"rank {rank} → {chunk.paper_title} p{chunk.page_number}")
    for missed in sorted(gold, key=lambda ref: (str(ref.paper_id), ref.page_number)):
        if missed not in matched:
            detail.append(f"missed → {missed.paper_id} p{missed.page_number}")

    return CaseScore(
        case_id=case.id,
        k=k,
        retrieved=len(retrieved),
        relevant_retrieved=relevant_retrieved,
        gold_total=gold_total,
        hit=hit,
        recall=recall,
        precision=precision,
        reciprocal_rank=reciprocal_rank,
        first_relevant_rank=ranks[0] if ranks else None,
        detail=detail,
    )


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


@dataclass
class AggregateScores:
    """Macro-averaged retrieval metrics over a set of cases."""

    k: int
    case_count: int
    hit_rate: float
    recall_at_k: float
    precision_at_k: float
    mrr_at_k: float

    def as_dict(self) -> dict:
        return {
            "k": self.k,
            "case_count": self.case_count,
            "hit_rate": round(self.hit_rate, 4),
            "recall_at_k": round(self.recall_at_k, 4),
            "precision_at_k": round(self.precision_at_k, 4),
            "mrr_at_k": round(self.mrr_at_k, 4),
        }


def aggregate(scores: list[CaseScore], k: int) -> AggregateScores:
    """Macro-average per-case scores.

    An empty score list averages to 0.0 rather than raising: a run that
    resolved no cases is a legitimate (and reportable) result, and the
    report says so separately via ``case_count``.
    """
    if not scores:
        return AggregateScores(
            k=k,
            case_count=0,
            hit_rate=0.0,
            recall_at_k=0.0,
            precision_at_k=0.0,
            mrr_at_k=0.0,
        )

    count = len(scores)
    return AggregateScores(
        k=k,
        case_count=count,
        hit_rate=sum(1.0 for s in scores if s.hit) / count,
        recall_at_k=sum(s.recall for s in scores) / count,
        precision_at_k=sum(s.precision for s in scores) / count,
        mrr_at_k=sum(s.reciprocal_rank for s in scores) / count,
    )


def compare(
    baseline: AggregateScores,
    candidate: AggregateScores,
) -> dict[str, dict[str, float]]:
    """Signed deltas from *baseline* to *candidate*, for every metric.

    Deltas are reported rather than a pass/fail verdict on purpose: a
    metric moving 0.02 on a 20-case dataset is noise, and the dataset
    size is right there in the same report for whoever reads it to judge.
    """
    metrics = (
        ("hit_rate", baseline.hit_rate, candidate.hit_rate),
        ("recall_at_k", baseline.recall_at_k, candidate.recall_at_k),
        ("precision_at_k", baseline.precision_at_k, candidate.precision_at_k),
        ("mrr_at_k", baseline.mrr_at_k, candidate.mrr_at_k),
    )
    return {
        name: {
            "baseline": round(before, 4),
            "candidate": round(after, 4),
            "delta": round(after - before, 4),
        }
        for name, before, after in metrics
    }
