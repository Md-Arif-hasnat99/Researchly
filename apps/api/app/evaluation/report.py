"""Run reports and reproducibility (FR-16).

FR-16 requires that "evaluation results should be reproducible". In
practice that means a number is only meaningful next to enough context
to tell whether two runs are comparable at all, so every report records:

- the dataset's version **and** content hash, so an edited eval set can
  never be silently compared against an older run;
- the git commit, so the code under test is pinned;
- every model involved, with the judge prompt version, because the
  judged metrics move when the rubric changes;
- the retrieval configuration, since a metric change from "we turned
  reranking on" and one from "we changed the dataset" are different
  findings.

Serialisation is deterministic — sorted keys, no wall-clock inside the
metric blocks — so re-running an unchanged configuration and diffing the
two JSON reports shows only what genuinely moved. The timestamp is
recorded once, at the top level, and deliberately excluded from the
hash of the results.
"""

import json
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from app.evaluation.dataset import EvalDataset
from app.evaluation.judge import (
    GENERATION_METRICS,
    JUDGE_PROMPT_VERSION,
    Judgement,
)
from app.evaluation.metrics import AggregateScores, CaseScore, compare
from app.schemas.search import SearchResultChunk

REPORT_VERSION = 1


def git_commit() -> str | None:
    """Current commit, or None outside a checkout.

    Best-effort by design: a missing commit must not stop an
    evaluation, but the report should show that provenance was
    unavailable rather than implying it was captured.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


# ---------------------------------------------------------------------------
# Cases and results
# ---------------------------------------------------------------------------


@dataclass
class CaseResult:
    """Everything measured for one evaluation case."""

    case_id: str
    question: str
    tags: list[str] = field(default_factory=list)
    expected_characteristics: list[str] = field(default_factory=list)
    """What a human said a good answer should contain.

    Recorded in the report for review and deliberately kept away from the
    judge prompt: showing the judge the expected content would have it
    grade against the answer key rather than against the system's own
    behaviour.
    """
    retrieved: list[SearchResultChunk] = field(default_factory=list)
    answer: str = ""
    citations: list[str] = field(default_factory=list)
    """Chunk IDs the answer cited, in citation order."""

    retrieval: CaseScore | None = None
    judgements: list[Judgement] = field(default_factory=list)
    error: str | None = None
    """Set when the case could not be run at all."""

    def as_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "question": self.question,
            "tags": self.tags,
            "expected_characteristics": self.expected_characteristics,
            "retrieval": {
                "retrieved_count": self.retrieval.retrieved,
                "relevant_retrieved": self.retrieval.relevant_retrieved,
                "gold_total": self.retrieval.gold_total,
                "hit": self.retrieval.hit,
                "recall": round(self.retrieval.recall, 4),
                "precision": round(self.retrieval.precision, 4),
                "reciprocal_rank": round(self.retrieval.reciprocal_rank, 4),
                "first_relevant_rank": self.retrieval.first_relevant_rank,
                "detail": self.retrieval.detail,
            }
            if self.retrieval
            else None,
            "answer": self.answer,
            "citations": self.citations,
            "judgements": [j.as_dict() for j in self.judgements],
            "error": self.error,
            "retrieved_chunks": [
                {
                    "paper_title": chunk.paper_title,
                    "page_number": chunk.page_number,
                    "similarity_score": chunk.similarity_score,
                    "matched_by": chunk.matched_by,
                }
                for chunk in self.retrieved
            ],
        }


# ---------------------------------------------------------------------------
# Generation aggregates
# ---------------------------------------------------------------------------


@dataclass
class GenerationAggregate:
    """Mean per judged metric, with unscored counts kept visible."""

    means: dict[str, float | None] = field(default_factory=dict)
    scored_counts: dict[str, int] = field(default_factory=dict)
    unscored_counts: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            metric: {
                "mean": None if mean is None else round(mean, 4),
                "scored": self.scored_counts.get(metric, 0),
                "unscored": self.unscored_counts.get(metric, 0),
            }
            for metric, mean in self.means.items()
        }


def aggregate_generation(results: list[CaseResult]) -> GenerationAggregate:
    """Average judged metrics across cases, tracking unscored counts."""
    aggregate = GenerationAggregate()
    for metric in GENERATION_METRICS:
        values: list[float] = []
        unscored = 0
        for result in results:
            for judgement in result.judgements:
                if judgement.metric != metric:
                    continue
                if judgement.scored:
                    values.append(judgement.score if judgement.score is not None else 0.0)
                else:
                    unscored += 1
        aggregate.means[metric] = (sum(values) / len(values)) if values else None
        aggregate.scored_counts[metric] = len(values)
        aggregate.unscored_counts[metric] = unscored
    return aggregate


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


@dataclass
class EvalReport:
    """A complete, self-describing evaluation run."""

    dataset: EvalDataset
    config: dict
    """Retrieval configuration under test: mode, rerank, k, threshold."""

    retrieval: AggregateScores | None = None
    generation: GenerationAggregate | None = None
    results: list[CaseResult] = field(default_factory=list)
    unresolved_case_ids: list[str] = field(default_factory=list)
    """Cases skipped because their gold papers were not in the library."""

    models: dict[str, str] = field(default_factory=dict)
    judge_prompt_version: int = JUDGE_PROMPT_VERSION

    report_version: int = REPORT_VERSION
    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    git_commit: str | None = field(default_factory=git_commit)

    # -- serialisation ----------------------------------------------------

    def manifest(self) -> dict:
        """Provenance needed to decide whether two runs are comparable."""
        return {
            "report_version": self.report_version,
            "generated_at": self.generated_at,
            "git_commit": self.git_commit,
            "dataset": self.dataset.summary(),
            "config": self.config,
            "models": self.models,
            "judge_prompt_version": self.judge_prompt_version,
            "cases_run": len(self.results),
            "cases_unresolved": self.unresolved_case_ids,
        }

    def as_dict(self) -> dict:
        return {
            "manifest": self.manifest(),
            "retrieval": self.retrieval.as_dict() if self.retrieval else None,
            "generation": self.generation.as_dict() if self.generation else None,
            "cases": [result.as_dict() for result in self.results],
        }

    def to_json(self) -> str:
        """Deterministic JSON: sorted keys, fixed separators, trailing newline."""
        return (
            json.dumps(self.as_dict(), indent=2, sort_keys=True, ensure_ascii=False)
            + "\n"
        )

    def save(self, path: str | Path) -> Path:
        file_path = Path(path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(self.to_json(), encoding="utf-8")
        return file_path

    # -- comparison -------------------------------------------------------

    def comparable_to(self, other: "EvalReport") -> tuple[bool, list[str]]:
        """Whether a baseline's numbers may be diffed against this run.

        Returns ``(ok, reasons)``. Comparability is checked before any
        delta is shown, because a delta between two runs that differ in
        the dataset or the judge rubric is a meaningless number that
        looks exactly like a real finding.
        """
        reasons: list[str] = []
        if self.dataset.content_hash != other.dataset.content_hash:
            reasons.append(
                "dataset content hash differs — the eval set was edited between runs"
            )
        if self.judge_prompt_version != other.judge_prompt_version:
            reasons.append(
                f"judge prompt version differs "
                f"({other.judge_prompt_version} → {self.judge_prompt_version})"
            )
        if set(self.models) != set(other.models):
            reasons.append("a different set of models was involved")
        elif any(self.models[k] != other.models[k] for k in self.models):
            differing = sorted(
                k for k in self.models if self.models[k] != other.models[k]
            )
            reasons.append(f"model(s) changed: {', '.join(differing)}")
        return (not reasons, reasons)

    def compare_to(self, baseline: "EvalReport") -> dict:
        """Deltas against *baseline*, with a comparability verdict.

        Only the retrieval metrics are diffed. The judged generation
        metrics are reported side by side but never differenced: they come
        from a stochastic judge, and subtracting two noisy numbers
        invites over-reading a difference that is really variance.
        """
        comparable, reasons = self.comparable_to(baseline)

        result: dict = {
            "comparable": comparable,
            "incomparable_reasons": reasons,
            "config_change": {
                key: {
                    "baseline": baseline.config.get(key),
                    "candidate": self.config.get(key),
                }
                for key in sorted(set(self.config) | set(baseline.config))
                if baseline.config.get(key) != self.config.get(key)
            },
        }

        if self.retrieval and baseline.retrieval:
            result["retrieval_delta"] = compare(baseline.retrieval, self.retrieval)

        if self.generation and baseline.generation:
            result["generation_comparison"] = {
                metric: {
                    "baseline": baseline.generation.means.get(metric),
                    "candidate": self.generation.means.get(metric),
                }
                for metric in GENERATION_METRICS
            }
        return result


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def render_markdown(report: EvalReport, comparison: dict | None = None) -> str:
    """Human-readable summary of a run.

    Numbers first, provenance immediately after, then the cases that
    scored worst — which is the only part most readers actually act on.
    """
    manifest = report.manifest()
    dataset_info = manifest["dataset"]
    lines: list[str] = [
        "# RAG evaluation",
        "",
        f"- Generated: `{manifest['generated_at']}`",
        f"- Commit: `{(manifest['git_commit'] or 'unavailable')[:12]}`",
        f"- Dataset: `{dataset_info['version']}` "
        f"({dataset_info['case_count']} cases, "
        f"{dataset_info['resolved_count']} resolved)",
        f"- Dataset hash: `{dataset_info['content_hash'][:12]}`",
    ]

    config = report.config
    lines.append(
        "- Config: "
        + ", ".join(f"{key}={config[key]}" for key in sorted(config))
    )
    if manifest["models"]:
        lines.append(
            "- Models: "
            + ", ".join(f"{k}={v}" for k, v in sorted(manifest["models"].items()))
        )
    if manifest["cases_unresolved"]:
        lines.append(
            f"- Unresolved (skipped): {', '.join(manifest['cases_unresolved'])}"
        )

    if report.retrieval:
        lines += ["", "## Retrieval", ""]
        if report.retrieval.case_count == 0:
            # A table of 0.0s here would read as a catastrophic score
            # rather than "nothing was measured". Say which it is.
            lines.append(
                "**No cases ran**, so there are no retrieval metrics. Every case "
                "was skipped: check `cases_unresolved` in the manifest for gold "
                "papers missing from this library."
            )
        else:
            lines.append(f"Cutoff K = {report.retrieval.k}")
            lines.append("")
            lines.append("| Metric | Value |")
            lines.append("| --- | --- |")
            for name, value in report.retrieval.as_dict().items():
                if name in {"k", "case_count"}:
                    continue
                lines.append(f"| {name} | {value} |")

    if report.generation and any(
        v is not None for v in report.generation.means.values()
    ):
        lines += ["", "## Generation (LLM-judged)", ""]
        lines.append(
            f"Judge prompt v{report.judge_prompt_version}. Unscored judgements "
            "are excluded from the mean, not counted as zero."
        )
        lines.append("")
        lines.append("| Metric | Mean | Scored | Unscored |")
        lines.append("| --- | --- | --- | --- |")
        for metric, stats in report.generation.as_dict().items():
            mean = stats["mean"]
            lines.append(
                f"| {metric} | {'—' if mean is None else mean} | "
                f"{stats['scored']} | {stats['unscored']} |"
            )

    if comparison:
        lines += ["", "## Comparison with baseline", ""]
        if not comparison["comparable"]:
            lines.append(
                "**Not comparable:** "
                + "; ".join(comparison["incomparable_reasons"])
                + ". Deltas are suppressed because they would not mean anything."
            )
        else:
            if comparison.get("config_change"):
                lines.append("Configuration changed:")
                for key, values in comparison["config_change"].items():
                    lines.append(
                        f"- {key}: `{values['baseline']}` → `{values['candidate']}`"
                    )
                lines.append("")
            lines.append("| Metric | Baseline | Candidate | Delta |")
            lines.append("| --- | --- | --- | --- |")
            for name, values in (comparison.get("retrieval_delta") or {}).items():
                lines.append(
                    f"| {name} | {values['baseline']} | {values['candidate']} | "
                    f"{values['delta']:+} |"
                )

    misses = [r for r in report.results if r.retrieval and not r.retrieval.hit]
    if misses:
        lines += ["", "## Misses", ""]
        for result in misses[:10]:
            lines.append(f"- `{result.case_id}`: {result.question}")
            for entry in result.retrieval.detail or []:
                lines.append(f"  - {entry}")

    return "\n".join(lines) + "\n"
