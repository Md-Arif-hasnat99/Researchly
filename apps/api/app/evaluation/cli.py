"""Command-line entry point for FR-16 evaluation.

    python -m app.evaluation --dataset datasets/example.json --user-id <uuid>

Writes a JSON report (and optionally Markdown) that records the dataset
hash, commit, models and configuration, so two runs can be compared
later with ``--baseline``.

Retrieval-only runs cost nothing and need no API key:

    python -m app.evaluation --dataset datasets/example.json \\
        --user-id <uuid> --no-generate
"""

import argparse
import json
import logging
import sys
from pathlib import Path

from app.evaluation.dataset import load_dataset
from app.evaluation.judge import GENERATION_METRICS
from app.evaluation.report import EvalReport, render_markdown
from app.evaluation.runner import EvalConfig, run_evaluation

logger = logging.getLogger("researchly")

DEFAULT_DATASET = Path(__file__).parent / "datasets" / "example.json"


def _echo(text: str = "") -> None:
    """Write to stdout without dying on a console that cannot encode the text.

    Reports echo dataset questions, paper titles and section names, and the
    comparison table uses an arrow, so non-ASCII output is normal rather than
    exceptional. A Windows console defaults to cp1252 and would raise
    UnicodeEncodeError part way through printing a report that had already
    been written to disk, which reads as a failed run that actually
    succeeded. Unrepresentable characters are replaced rather than fatal.
    """
    try:
        print(text)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "ascii"
        print(text.encode(encoding, "replace").decode(encoding, "replace"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.evaluation",
        description="Evaluate RAG retrieval and generation quality (FR-16).",
    )
    parser.add_argument(
        "--dataset",
        default=str(DEFAULT_DATASET),
        help="Path to an evaluation dataset JSON file.",
    )
    parser.add_argument(
        "--user-id",
        required=True,
        help="UUID of the library owner to evaluate against.",
    )
    parser.add_argument(
        "--k",
        type=int,
        default=5,
        help="Result cutoff to score at (default: 5).",
    )
    parser.add_argument(
        "--mode",
        choices=("hybrid", "vector", "keyword"),
        default="hybrid",
        help="Retrieval mode to evaluate (default: hybrid).",
    )
    rerank_group = parser.add_mutually_exclusive_group()
    rerank_group.add_argument(
        "--rerank",
        dest="rerank",
        action="store_true",
        default=EvalConfig.rerank,
        help="Evaluate with FR-15 reranking enabled (default, as shipped).",
    )
    rerank_group.add_argument(
        "--no-rerank",
        dest="rerank",
        action="store_false",
        help="Evaluate without reranking, for the baseline arm of an A/B.",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.65,
        help="Minimum cosine similarity for vector retrieval (default: 0.65).",
    )
    parser.add_argument(
        "--no-generate",
        dest="generate",
        action="store_false",
        default=True,
        help="Score retrieval only; skips generation and the LLM judge.",
    )
    parser.add_argument(
        "--metrics",
        default=",".join(GENERATION_METRICS),
        help=(
            "Comma-separated judged metrics to run "
            f"(default: {','.join(GENERATION_METRICS)})."
        ),
    )
    parser.add_argument(
        "--out",
        help="Write the JSON report to this path.",
    )
    parser.add_argument(
        "--markdown",
        help="Write a Markdown summary to this path.",
    )
    parser.add_argument(
        "--baseline",
        help="Path to a previous JSON report to compare against.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Log per-case progress.",
    )
    return parser


def _load_baseline(path: str) -> dict:
    """Read a previous report's summary for comparison.

    Only the manifest and aggregates are needed, so a baseline is loaded
    as plain JSON rather than reconstructed into an EvalReport. Its
    dataset cannot be re-hashed from here, so the comparison falls back
    to the hashes recorded in the file.
    """
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _compare_against_file(report: EvalReport, baseline: dict) -> dict:
    """Compare against a report loaded from disk.

    Mirrors :meth:`EvalReport.compare_to` but sources the dataset hash
    from the stored manifest, since the original dataset object is not
    available.
    """
    baseline_hash = (
        baseline.get("manifest", {}).get("dataset", {}).get("content_hash")
    )
    candidate_hash = report.dataset.content_hash

    reasons: list[str] = []
    if baseline_hash != candidate_hash:
        reasons.append("dataset content hash differs - the eval set was edited between runs")
    if baseline.get("manifest", {}).get("judge_prompt_version") != report.judge_prompt_version:
        reasons.append("judge prompt version differs between runs")

    # Same model check the in-memory comparison makes. A run that swapped
    # the generation model moves the judged metrics, and their deltas are
    # exactly the numbers a reader is most likely to over-trust.
    baseline_models = baseline.get("manifest", {}).get("models", {}) or {}
    if baseline_models != report.models:
        changed = sorted(
            set(baseline_models) | set(report.models),
            key=str,
        )
        reasons.append(
            "model(s) differ between runs: "
            + ", ".join(
                f"{name} {baseline_models.get(name, 'none')} -> "
                f"{report.models.get(name, 'none')}"
                for name in changed
            )
        )

    comparison: dict = {
        "comparable": not reasons,
        "incomparable_reasons": reasons,
    }

    baseline_config = baseline.get("manifest", {}).get("config", {})
    comparison["config_change"] = {
        key: {"baseline": baseline_config.get(key), "candidate": report.config.get(key)}
        for key in sorted(set(baseline_config) | set(report.config))
        if baseline_config.get(key) != report.config.get(key)
    }

    baseline_retrieval = baseline.get("retrieval")
    if baseline_retrieval and report.retrieval:
        from app.evaluation.metrics import AggregateScores, compare

        comparison["retrieval_delta"] = compare(
            AggregateScores(
                k=baseline_retrieval["k"],
                case_count=baseline_retrieval["case_count"],
                hit_rate=baseline_retrieval["hit_rate"],
                recall_at_k=baseline_retrieval["recall_at_k"],
                precision_at_k=baseline_retrieval["precision_at_k"],
                mrr_at_k=baseline_retrieval["mrr_at_k"],
            ),
            report.retrieval,
        )

    baseline_generation = baseline.get("generation") or {}
    if baseline_generation and report.generation:
        comparison["generation_comparison"] = {
            metric: {
                "baseline": baseline_generation.get(metric, {}).get("mean"),
                "candidate": report.generation.means.get(metric),
            }
            for metric in GENERATION_METRICS
        }

    return comparison


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    # Ask the terminal for UTF-8 first; _echo() covers the streams that
    # cannot be reconfigured.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError, ValueError):  # pragma: no cover - exotic streams
        pass
    # The app's logging module already installs a handler on the
    # "researchly" logger, so calling basicConfig() here would add a
    # second one on the root logger and print every record twice.
    app_logger = logging.getLogger("researchly")
    if not app_logger.handlers:
        logging.basicConfig(
            level=logging.INFO if args.verbose else logging.WARNING,
            format="%(levelname)s %(name)s: %(message)s",
        )
    app_logger.setLevel(logging.INFO if args.verbose else logging.WARNING)

    try:
        dataset = load_dataset(args.dataset)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Dataset error: {exc}", file=sys.stderr)
        return 2

    metrics = tuple(m.strip() for m in args.metrics.split(",") if m.strip())
    unknown = [m for m in metrics if m not in GENERATION_METRICS]
    if unknown:
        print(
            f"Unknown metrics: {', '.join(unknown)}. "
            f"Choose from: {', '.join(GENERATION_METRICS)}",
            file=sys.stderr,
        )
        return 2

    config = EvalConfig(
        k=args.k,
        mode=args.mode,
        rerank=args.rerank,
        similarity_threshold=args.threshold,
        generate=args.generate,
        judge_metrics=metrics,
    )

    try:
        report = run_evaluation(dataset=dataset, user_id=args.user_id, config=config)
    except Exception as exc:  # noqa: BLE001
        print(f"Evaluation failed: {exc}", file=sys.stderr)
        logger.debug("Evaluation traceback", exc_info=True)
        return 1

    comparison = None
    if args.baseline:
        try:
            comparison = _compare_against_file(report, _load_baseline(args.baseline))
        except (OSError, ValueError) as exc:
            print(f"Baseline error: {exc}", file=sys.stderr)
            return 2

    if args.out:
        path = report.save(args.out)
        _echo(f"JSON report: {path}")
    else:
        _echo(report.to_json())

    markdown = render_markdown(report, comparison)
    if args.markdown:
        md_path = Path(args.markdown)
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(markdown, encoding="utf-8")
        _echo(f"Markdown summary: {md_path}")
    else:
        _echo()
        _echo(markdown)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
