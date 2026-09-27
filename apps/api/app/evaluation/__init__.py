"""RAG evaluation harness (FR-16).

Measures retrieval and generation quality against a fixed, human-labelled
dataset so changes to the retrieval stack can be justified with numbers
instead of intuition — which is what FR-15 asked for when it said the
reranker "should be evaluated rather than added without evidence of
improvement".

Layout:

- :mod:`~app.evaluation.dataset` — dataset schema, validation, gold
  resolution, content hashing.
- :mod:`~app.evaluation.metrics` — deterministic retrieval metrics
  (hit rate, recall@k, precision@k, MRR). No I/O.
- :mod:`~app.evaluation.judge` — LLM-judged generation metrics.
- :mod:`~app.evaluation.runner` — orchestrates a run.
- :mod:`~app.evaluation.report` — reproducible reports and comparison.
- :mod:`~app.evaluation.cli` — ``python -m app.evaluation``.

Run it with::

    python -m app.evaluation --dataset app/evaluation/datasets/example.json \\
        --user-id <uuid> --no-generate
"""

from app.evaluation.dataset import EvalCase, EvalDataset, load_dataset, resolve_gold
from app.evaluation.judge import GENERATION_METRICS, Judgement, judge_metric
from app.evaluation.metrics import (
    AggregateScores,
    CaseScore,
    aggregate,
    score_case,
)
from app.evaluation.report import EvalReport, render_markdown
from app.evaluation.runner import EvalConfig, run_evaluation

__all__ = [
    "GENERATION_METRICS",
    "AggregateScores",
    "CaseScore",
    "EvalCase",
    "EvalConfig",
    "EvalDataset",
    "EvalReport",
    "Judgement",
    "aggregate",
    "judge_metric",
    "load_dataset",
    "render_markdown",
    "resolve_gold",
    "run_evaluation",
    "score_case",
]
