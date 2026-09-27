"""Tests for the FR-16 evaluation harness.

Two things are being verified here, in order of importance:

1. **The metric arithmetic is right.** Expected values are hand-computed
   from the definitions in :mod:`app.evaluation.metrics` rather than
   produced by the code under test, because a metrics library that
   agrees with itself is exactly the failure mode FR-16 exists to
   prevent.
2. **Failures are not silently converted into scores.** An unreadable
   judge reply must be *unscored*, a case whose gold paper is missing
   from the library must be *skipped*, and two runs on different datasets
   must refuse to be differenced.
"""

import json
import sys
from uuid import UUID, uuid4

import pytest

from app.evaluation.dataset import (
    EvalCase,
    EvalDataset,
    GoldPage,
    GoldRef,
    load_dataset,
    load_dataset_from_dict,
    resolve_gold,
)
from app.evaluation.judge import (
    GENERATION_METRICS,
    Judgement,
    _parse_judgement,
    average_scores,
    judge_metric,
)
from app.evaluation.metrics import (
    aggregate,
    compare,
    is_relevant,
    relevant_ranks,
    score_case,
)
from app.evaluation.report import (
    CaseResult,
    EvalReport,
    GenerationAggregate,
    aggregate_generation,
    render_markdown,
)
from app.evaluation.runner import EvalConfig, run_evaluation
from app.schemas.search import SearchResultChunk

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PAPER_A = uuid4()
PAPER_B = uuid4()


def _chunk(paper_id: UUID, page: int, title: str = "Paper") -> SearchResultChunk:
    return SearchResultChunk(
        chunk_id=uuid4(),
        paper_id=paper_id,
        paper_title=title,
        page_number=page,
        section="Methods",
        content=f"Content for page {page}.",
        similarity_score=0.8,
        matched_by=["vector"],
    )


def _case(
    case_id: str = "c1",
    gold: list[tuple[UUID, int]] | None = None,
    characteristics: list[str] | None = None,
) -> EvalCase:
    return EvalCase(
        id=case_id,
        question="What does the paper say?",
        expected_pages=[
            GoldPage(paper_title="Paper", page_number=page, paper_id=paper_id)
            for paper_id, page in (gold or [(PAPER_A, 3)])
        ],
        expected_answer_characteristics=(
            characteristics if characteristics is not None else ["cites a number"]
        ),
    )


def _dataset(*cases: EvalCase) -> EvalDataset:
    return EvalDataset(
        version="test-1",
        description="test dataset",
        cases=list(cases),
    )


# ---------------------------------------------------------------------------
# Relevance
# ---------------------------------------------------------------------------


class TestRelevance:
    def test_page_is_part_of_the_label(self):
        """Right paper, wrong page is not relevant."""
        chunk = _chunk(PAPER_A, page=7)
        gold = {GoldRef(paper_id=PAPER_A, page_number=9)}
        assert is_relevant(chunk, gold) is False

    def test_matching_paper_and_page_is_relevant(self):
        chunk = _chunk(PAPER_A, page=7)
        gold = {GoldRef(paper_id=PAPER_A, page_number=7)}
        assert is_relevant(chunk, gold) is True

    def test_ranks_are_one_based_and_ordered(self):
        retrieved = [
            _chunk(PAPER_A, 1),
            _chunk(PAPER_A, 2),
            _chunk(PAPER_A, 3),
        ]
        gold = {GoldRef(paper_id=PAPER_A, page_number=2)}
        assert relevant_ranks(retrieved, gold, 3) == [2]

    def test_ranks_respect_the_cutoff(self):
        retrieved = [_chunk(PAPER_A, 1), _chunk(PAPER_A, 2)]
        gold = {GoldRef(paper_id=PAPER_A, page_number=2)}
        # The hit is at rank 2, outside a K of 1.
        assert relevant_ranks(retrieved, gold, 1) == []

    def test_cutoff_is_measured_from_the_top(self):
        """K=2 means the first two results, not any two results."""
        retrieved = [
            _chunk(PAPER_A, 1),
            _chunk(PAPER_A, 2),
            _chunk(PAPER_A, 3),  # the gold page, ranked third
        ]
        gold = {GoldRef(paper_id=PAPER_A, page_number=3)}
        assert relevant_ranks(retrieved, gold, 2) == []
        assert relevant_ranks(retrieved, gold, 3) == [3]


# ---------------------------------------------------------------------------
# Per-case scoring — hand-computed expectations
# ---------------------------------------------------------------------------


class TestScoreCase:
    def test_first_position_hit(self):
        """Gold at rank 1 of 5: hit, recall 1, precision 0.2, RR 1.0."""
        retrieved = [
            _chunk(PAPER_A, 3),
            _chunk(PAPER_A, 4),
            _chunk(PAPER_A, 5),
            _chunk(PAPER_A, 6),
            _chunk(PAPER_A, 7),
        ]
        result = score_case(_case(), retrieved, k=5)

        assert result.hit is True
        assert result.relevant_retrieved == 1
        assert result.recall == 1.0
        # 1 relevant of K=5: precision is a penalty on padding, so it is
        # 0.2 and not a perfect score for a correct first hit.
        assert result.precision == pytest.approx(0.2)
        assert result.reciprocal_rank == 1.0
        assert result.first_relevant_rank == 1

    def test_second_position_hit(self):
        """Gold at rank 2 of 3: RR = 0.5."""
        retrieved = [
            _chunk(PAPER_A, 1),
            _chunk(PAPER_A, 3),
            _chunk(PAPER_A, 4),
        ]
        result = score_case(_case(), retrieved, k=3)
        assert result.reciprocal_rank == pytest.approx(0.5)
        assert result.hit is True

    def test_partial_recall_with_two_gold_pages(self):
        """Finds 1 of 2 gold pages: hit, but recall is only 0.5."""
        retrieved = [
            _chunk(PAPER_A, 3),
            _chunk(PAPER_A, 99),
            _chunk(PAPER_B, 5),
        ]
        result = score_case(
            _case(gold=[(PAPER_A, 3), (PAPER_A, 4)]),
            retrieved,
            k=3,
        )
        assert result.hit is True
        assert result.gold_total == 2
        assert result.relevant_retrieved == 1
        assert result.recall == pytest.approx(0.5)
        # 1 relevant in the top 3.
        assert result.precision == pytest.approx(1 / 3)
        assert "missed" in " ".join(result.detail)

    def test_full_recall_with_two_gold_pages(self):
        retrieved = [_chunk(PAPER_A, 3), _chunk(PAPER_A, 4)]
        result = score_case(_case(gold=[(PAPER_A, 3), (PAPER_A, 4)]), retrieved, k=5)
        assert result.recall == pytest.approx(1.0)
        assert result.precision == pytest.approx(0.4)

    def test_no_hit_scores_zero_everywhere(self):
        retrieved = [_chunk(PAPER_B, 1), _chunk(PAPER_B, 2)]
        result = score_case(_case(), retrieved, k=2)
        assert result.hit is False
        assert result.recall == 0.0
        assert result.precision == 0.0
        assert result.reciprocal_rank == 0.0
        assert result.first_relevant_rank is None

    def test_duplicate_pages_count_once(self):
        """The same gold page returned three times is one piece of evidence.

        Without this, a retriever that repeats a single hit could reach
        recall and precision 1.0 without having found anything else.
        """
        hit = _chunk(PAPER_A, 3)
        retrieved = [hit, hit.model_copy(), hit.model_copy()]
        result = score_case(_case(), retrieved, k=3)
        assert result.relevant_retrieved == 1
        assert result.recall == pytest.approx(1.0)
        assert result.precision == pytest.approx(1 / 3)

    def test_reported_retrieval_count_is_before_the_cutoff(self):
        retrieved = [_chunk(PAPER_A, page) for page in range(1, 9)]
        result = score_case(_case(), retrieved, k=3)
        assert result.retrieved == 8
        # But only the top 3 counted.
        assert result.relevant_retrieved <= 3

    def test_empty_retrieval_scores_zero(self):
        result = score_case(_case(), [], k=5)
        assert result.hit is False
        assert result.recall == 0.0
        assert result.retrieved == 0

    def test_unresolved_case_refuses_to_score(self):
        """Scoring against unresolved gold would report a spurious zero."""
        unresolved = EvalCase(
            id="c-unresolved",
            question="q",
            expected_pages=[GoldPage(paper_title="Missing", page_number=2)],
        )
        with pytest.raises(ValueError, match="unresolved"):
            score_case(unresolved, [_chunk(PAPER_A, 2)], k=3)


# ---------------------------------------------------------------------------
# Aggregation — hand-computed expectations
# ---------------------------------------------------------------------------


class TestAggregate:
    def test_macro_average_over_cases(self):
        """Two cases, one hit and one total miss.

        A micro average over chunks would not give these numbers, which
        is why the mean is taken per case.
        """
        perfect = score_case(
            _case("perfect"),
            [_chunk(PAPER_A, 3), _chunk(PAPER_A, 4)],
            k=2,
        )
        miss = score_case(
            _case("miss"),
            [_chunk(PAPER_B, 1), _chunk(PAPER_B, 2)],
            k=2,
        )
        result = aggregate([perfect, miss], k=2)

        assert result.case_count == 2
        # Hit rate: 1 of 2 cases found its gold page.
        assert result.hit_rate == pytest.approx(0.5)
        # Recall: (1.0 + 0.0) / 2.
        assert result.recall_at_k == pytest.approx(0.5)
        # Precision: the hit case found 1 relevant chunk in K=2 (0.5) and
        # the miss case found none, so (0.5 + 0.0) / 2.
        assert result.precision_at_k == pytest.approx(0.25)
        # MRR: (1.0 + 0.0) / 2.
        assert result.mrr_at_k == pytest.approx(0.5)

    def test_hit_rate_and_recall_differ(self):
        """A case can hit while missing half its gold pages.

        Hit rate alone would score this 1.0; recall exposes that only one
        of the two acceptable pages was found.
        """
        partial = score_case(
            _case("partial", gold=[(PAPER_A, 3), (PAPER_A, 4)]),
            [_chunk(PAPER_A, 3), _chunk(PAPER_A, 9)],
            k=2,
        )
        result = aggregate([partial], k=2)
        assert result.hit_rate == pytest.approx(1.0)
        assert result.recall_at_k == pytest.approx(0.5)

    def test_mrr_only_counts_the_first_hit(self):
        retrieved = [
            _chunk(PAPER_A, 1),
            _chunk(PAPER_A, 3),
            _chunk(PAPER_A, 4),
        ]
        result = aggregate(
            [score_case(_case(gold=[(PAPER_A, 3), (PAPER_A, 4)]), retrieved, 3)], k=3
        )
        # Found at rank 2, so 1/2 — not 1/2 + 1/3.
        assert result.mrr_at_k == pytest.approx(0.5)
        assert result.recall_at_k == pytest.approx(1.0)

    def test_no_cases_aggregates_to_zero_without_raising(self):
        result = aggregate([], k=5)
        assert result.case_count == 0
        assert result.hit_rate == 0.0
        assert result.recall_at_k == 0.0

    def test_as_dict_is_rounded(self):
        retrieved = [_chunk(PAPER_A, 3), _chunk(PAPER_B, 1)]
        result = aggregate([score_case(_case(), retrieved, k=3)], k=3)
        assert result.as_dict()["precision_at_k"] == pytest.approx(0.3333, abs=1e-4)


class TestCompare:
    def test_deltas_are_signed(self):
        baseline = aggregate(
            [score_case(_case(), [_chunk(PAPER_B, 1), _chunk(PAPER_B, 2)], k=2)],
            k=2,
        )
        candidate = aggregate(
            [score_case(_case(), [_chunk(PAPER_A, 3), _chunk(PAPER_B, 1)], k=2)],
            k=2,
        )
        deltas = compare(baseline, candidate)
        assert deltas["hit_rate"]["delta"] == pytest.approx(1.0)
        assert deltas["mrr_at_k"]["delta"] == pytest.approx(1.0)

    def test_no_change_is_zero_delta(self):
        scores = [score_case(_case(), [_chunk(PAPER_A, 3)], k=1)]
        deltas = compare(aggregate(scores, 1), aggregate(scores, 1))
        assert deltas["hit_rate"]["delta"] == 0.0


# ---------------------------------------------------------------------------
# Dataset loading and validation
# ---------------------------------------------------------------------------


def _raw_dataset(**overrides) -> dict:
    raw = {
        "version": "v1",
        "description": "test",
        "cases": [
            {
                "id": "a",
                "question": "q1",
                "expected_pages": [{"paper_title": "P", "page_number": 1}],
            },
            {
                "id": "b",
                "question": "q2",
                "expected_pages": [{"paper_title": "P", "page_number": 2}],
            },
        ],
    }
    raw.update(overrides)
    return raw


class TestDataset:
    def test_loads_and_summarises(self, tmp_path):
        path = tmp_path / "d.json"
        path.write_text(json.dumps(_raw_dataset()), encoding="utf-8")
        dataset = load_dataset(path)

        assert dataset.version == "v1"
        assert len(dataset.cases) == 2
        summary = dataset.summary()
        assert summary["case_count"] == 2
        assert summary["resolved_count"] == 0

    def test_missing_file_raises_with_the_path(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="not found"):
            load_dataset(tmp_path / "nope.json")

    def test_invalid_json_raises_value_error(self, tmp_path):
        path = tmp_path / "d.json"
        path.write_text("{not json", encoding="utf-8")
        with pytest.raises(ValueError, match="not valid JSON"):
            load_dataset(path)

    def test_missing_version_is_rejected(self, tmp_path):
        raw = _raw_dataset()
        del raw["version"]
        path = tmp_path / "d.json"
        path.write_text(json.dumps(raw), encoding="utf-8")
        with pytest.raises(ValueError, match="version"):
            load_dataset(path)

    def test_empty_cases_are_rejected(self, tmp_path):
        path = tmp_path / "d.json"
        path.write_text(json.dumps(_raw_dataset(cases=[])), encoding="utf-8")
        with pytest.raises(ValueError, match="non-empty"):
            load_dataset(path)

    def test_case_without_gold_pages_is_rejected(self, tmp_path):
        """A case with no gold location cannot be scored for recall."""
        raw = _raw_dataset(
            cases=[{"id": "a", "question": "q", "expected_pages": []}]
        )
        path = tmp_path / "d.json"
        path.write_text(json.dumps(raw), encoding="utf-8")
        with pytest.raises(ValueError, match="invalid"):
            load_dataset(path)

    def test_page_zero_is_rejected(self, tmp_path):
        raw = _raw_dataset(
            cases=[
                {
                    "id": "a",
                    "question": "q",
                    "expected_pages": [{"paper_title": "P", "page_number": 0}],
                }
            ]
        )
        path = tmp_path / "d.json"
        path.write_text(json.dumps(raw), encoding="utf-8")
        with pytest.raises(ValueError, match="invalid"):
            load_dataset(path)

    def test_duplicate_case_ids_are_rejected(self, tmp_path):
        """Duplicate ids would make per-case scores ambiguous across runs."""
        page = {"paper_title": "P", "page_number": 1}
        raw = _raw_dataset(
            cases=[
                {"id": "same", "question": "q1", "expected_pages": [page]},
                {"id": "same", "question": "q2", "expected_pages": [page]},
            ]
        )
        path = tmp_path / "d.json"
        path.write_text(json.dumps(raw), encoding="utf-8")
        with pytest.raises(ValueError, match="duplicate case id"):
            load_dataset(path)

    def test_from_dict_requires_cases(self):
        with pytest.raises(ValueError, match="non-empty"):
            load_dataset_from_dict({"version": "v1", "cases": []})


class TestContentHash:
    def test_hash_is_stable_across_loads(self, tmp_path):
        path = tmp_path / "d.json"
        path.write_text(json.dumps(_raw_dataset()), encoding="utf-8")
        assert load_dataset(path).content_hash == load_dataset(path).content_hash

    def test_hash_ignores_reformatting(self, tmp_path):
        """Reindenting the file must not invalidate a baseline comparison."""
        path = tmp_path / "d.json"
        path.write_text(json.dumps(_raw_dataset()), encoding="utf-8")
        first = load_dataset(path).content_hash
        path.write_text(json.dumps(_raw_dataset(), indent=4), encoding="utf-8")
        assert load_dataset(path).content_hash == first

    def test_hash_ignores_description(self, tmp_path):
        path = tmp_path / "d.json"
        path.write_text(json.dumps(_raw_dataset()), encoding="utf-8")
        first = load_dataset(path).content_hash
        path.write_text(
            json.dumps(_raw_dataset(description="edited prose")), encoding="utf-8"
        )
        assert load_dataset(path).content_hash == first

    def test_hash_ignores_page_notes(self, tmp_path):
        """A note is prose for humans and must not move a metric."""
        base = _raw_dataset()
        path = tmp_path / "d.json"
        path.write_text(json.dumps(base), encoding="utf-8")
        first = load_dataset(path).content_hash

        annotated = _raw_dataset()
        annotated["cases"][0]["expected_pages"][0]["note"] = "checked by hand"
        path.write_text(json.dumps(annotated), encoding="utf-8")
        assert load_dataset(path).content_hash == first

    def test_hash_changes_when_a_page_changes(self, tmp_path):
        path = tmp_path / "d.json"
        path.write_text(json.dumps(_raw_dataset()), encoding="utf-8")
        first = load_dataset(path).content_hash
        raw = _raw_dataset()
        raw["cases"][0]["expected_pages"][0]["page_number"] = 99
        path.write_text(json.dumps(raw), encoding="utf-8")
        assert load_dataset(path).content_hash != first

    def test_hash_changes_when_a_question_changes(self, tmp_path):
        path = tmp_path / "d.json"
        path.write_text(json.dumps(_raw_dataset()), encoding="utf-8")
        first = load_dataset(path).content_hash
        raw = _raw_dataset()
        raw["cases"][0]["question"] = "reworded"
        path.write_text(json.dumps(raw), encoding="utf-8")
        assert load_dataset(path).content_hash != first


# ---------------------------------------------------------------------------
# Gold resolution
# ---------------------------------------------------------------------------


class TestResolveGold:
    def test_resolves_titles_to_ids(self):
        dataset = _dataset(
            EvalCase(
                id="c1",
                question="q",
                expected_pages=[GoldPage(paper_title="Deep Learning", page_number=4)],
            )
        )
        resolve_gold(dataset, {"Deep Learning": PAPER_A})
        assert dataset.cases[0].is_resolved
        assert dataset.resolved_cases()[0].gold_refs() == {
            GoldRef(paper_id=PAPER_A, page_number=4)
        }

    def test_unmatched_title_leaves_the_case_unresolved(self):
        dataset = _dataset(
            EvalCase(
                id="c1",
                question="q",
                expected_pages=[GoldPage(paper_title="Absent", page_number=1)],
            )
        )
        resolve_gold(dataset, {"Other": PAPER_A})
        assert not dataset.cases[0].is_resolved
        assert [c.id for c in dataset.unresolved_cases()] == ["c1"]

    def test_matching_tolerates_case_and_whitespace(self):
        """A hand-edited dataset should not fail on stray capitalisation."""
        dataset = _dataset(
            EvalCase(
                id="c1",
                question="q",
                expected_pages=[GoldPage(paper_title="deep  learning", page_number=1)],
            )
        )
        resolve_gold(dataset, {"Deep Learning": PAPER_A})
        assert dataset.cases[0].is_resolved

    def test_already_resolved_pages_are_left_alone(self):
        case = _case(gold=[(PAPER_A, 3)])
        dataset = _dataset(case)
        resolve_gold(dataset, {"Paper": PAPER_B})
        assert case.expected_pages[0].paper_id == PAPER_A


# ---------------------------------------------------------------------------
# Judge
# ---------------------------------------------------------------------------


class TestParseJudgement:
    def test_reads_a_well_formed_reply(self):
        judgement = _parse_judgement("faithfulness", '{"score": 0.75, "reason": "ok"}')
        assert judgement.score == pytest.approx(0.75)
        assert judgement.reason == "ok"
        assert judgement.scored

    def test_unparseable_json_is_unscored_not_zero(self):
        """A judge failure must not drag the mean down as a quality score."""
        judgement = _parse_judgement("faithfulness", "I think it is quite good")
        assert judgement.score is None
        assert judgement.scored is False
        assert "JSON" in judgement.error

    def test_missing_score_is_unscored(self):
        assert _parse_judgement("faithfulness", '{"reason": "ok"}').score is None

    def test_out_of_range_score_is_unscored_not_clamped(self):
        """A 7.0 is not a perfect 1.0; it is not on the scale."""
        judgement = _parse_judgement("faithfulness", '{"score": 7.0}')
        assert judgement.score is None
        assert "outside" in judgement.error

    def test_negative_score_is_unscored(self):
        assert _parse_judgement("faithfulness", '{"score": -0.5}').score is None

    def test_non_numeric_score_is_unscored(self):
        judgement = _parse_judgement("faithfulness", '{"score": "high"}')
        assert judgement.score is None
        assert "non-numeric" in judgement.error

    def test_boolean_is_not_treated_as_a_number(self):
        """bool is a subclass of int in Python; True must not score 1.0."""
        judgement = _parse_judgement("faithfulness", '{"score": true}')
        assert judgement.score is None

    def test_score_accepted_without_a_reason(self):
        judgement = _parse_judgement("faithfulness", '{"score": 0.5}')
        assert judgement.score == pytest.approx(0.5)
        assert judgement.reason == ""

    def test_array_reply_is_unscored(self):
        assert _parse_judgement("faithfulness", "[0.5]").score is None


class TestJudgeMetric:
    def test_unknown_metric_raises(self):
        with pytest.raises(ValueError, match="Unknown metric"):
            judge_metric("vibes", "q", "a", [])

    def test_missing_api_key_is_unscored(self):
        with patch_settings(api_key=""):
            judgement = judge_metric("faithfulness", "q", "an answer", [_chunk(PAPER_A, 1)])
        assert judgement.score is None
        assert "GEMINI_API_KEY" in judgement.error

    def test_empty_answer_is_unscored(self):
        with patch_settings(api_key="key"):
            judgement = judge_metric("faithfulness", "q", "   ", [_chunk(PAPER_A, 1)])
        assert judgement.score is None
        assert "no answer" in judgement.error

    def test_model_failure_is_unscored(self):
        with patch_settings(api_key="key"), patch_genai_failure(RuntimeError("boom")):
            judgement = judge_metric("faithfulness", "q", "an answer", [_chunk(PAPER_A, 1)])
        assert judgement.score is None
        assert "boom" in judgement.error

    def test_successful_call_returns_the_score(self):
        with patch_settings(api_key="key"), patch_genai_response(
            '{"score": 1.0, "reason": "fully supported"}'
        ) as client:
            judgement = judge_metric("faithfulness", "q", "an answer", [_chunk(PAPER_A, 1)])
        assert judgement.score == pytest.approx(1.0)
        # Greedy decoding is the determinism lever for a judge.
        config = client.models.generate_content.call_args[1]["config"]
        assert config.temperature == 0.0

    def test_prompt_carries_question_answer_and_numbered_excerpts(self):
        with patch_settings(api_key="key"), patch_genai_response('{"score": 1.0}') as client:
            judge_metric("citation_accuracy", "the question", "the answer", [_chunk(PAPER_A, 7)])
        prompt = client.models.generate_content.call_args[1]["contents"][0].parts[0].text
        assert "the question" in prompt
        assert "the answer" in prompt
        assert "Excerpt 1" in prompt
        assert "p7" in prompt
        assert "citation_accuracy" not in prompt

    def test_rubric_anchors_are_in_the_prompt(self):
        """A score has to mean something, so the anchors travel with it."""
        with patch_settings(api_key="key"), patch_genai_response('{"score": 0.5}') as client:
            judge_metric("faithfulness", "q", "a", [_chunk(PAPER_A, 1)])
        prompt = client.models.generate_content.call_args[1]["contents"][0].parts[0].text
        assert "1.0 —" in prompt
        assert "0.5 —" in prompt
        assert "0.0 —" in prompt


class TestAverageScores:
    def test_excludes_unscored_from_the_mean(self):
        scores = [
            Judgement(metric="faithfulness", score=1.0),
            Judgement(metric="faithfulness", score=None, error="failed"),
            Judgement(metric="faithfulness", score=0.0),
        ]
        # The unscored judgement is not a 0.
        assert average_scores(scores) == pytest.approx(0.5)

    def test_all_unscored_is_none_not_zero(self):
        scores = [Judgement(metric="faithfulness", score=None)]
        assert average_scores(scores) is None

    def test_empty_is_none(self):
        assert average_scores([]) is None

    def test_all_four_prd_metrics_are_covered(self):
        assert set(GENERATION_METRICS) == {
            "faithfulness",
            "answer_relevance",
            "context_relevance",
            "citation_accuracy",
        }


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


class TestGenerationAggregate:
    def test_tracks_scored_and_unscored_per_metric(self):
        results = [
            CaseResult(
                case_id="a",
                question="q",
                judgements=[
                    Judgement(metric="faithfulness", score=1.0),
                    Judgement(metric="answer_relevance", score=0.0),
                ],
            ),
            CaseResult(
                case_id="b",
                question="q",
                judgements=[
                    Judgement(metric="faithfulness", score=None, error="judge died"),
                ],
            ),
        ]
        aggregate_out = aggregate_generation(results)

        assert aggregate_out.means["faithfulness"] == pytest.approx(1.0)
        assert aggregate_out.scored_counts["faithfulness"] == 1
        assert aggregate_out.unscored_counts["faithfulness"] == 1
        assert aggregate_out.means["answer_relevance"] == pytest.approx(0.0)
        # A metric nobody judged is None, not 0.0.
        assert aggregate_out.means["citation_accuracy"] is None

    def test_as_dict_shape(self):
        aggregate_out = aggregate_generation(
            [CaseResult(case_id="a", question="q", judgements=[Judgement("faithfulness", 0.5)])]
        )
        entry = aggregate_out.as_dict()["faithfulness"]
        assert entry == {"mean": 0.5, "scored": 1, "unscored": 0}


class TestReportSerialisation:
    def _report(self, **overrides) -> EvalReport:
        report = EvalReport(
            dataset=_dataset(_case()),
            config=EvalConfig(k=5, rerank=True).as_dict(),
            retrieval=aggregate([score_case(_case(), [_chunk(PAPER_A, 3)], k=5)], 5),
            results=[],
            **overrides,
        )
        return report

    def test_json_is_deterministic(self):
        """Re-serialising must not reorder keys or change spacing."""
        report = self._report()
        assert report.to_json() == report.to_json()

    def test_json_round_trips(self):
        report = self._report()
        payload = json.loads(report.to_json())
        assert payload["manifest"]["config"]["rerank"] is True
        assert payload["retrieval"]["k"] == 5

    def test_manifest_records_dataset_hash_and_commit_field(self):
        payload = json.loads(self._report().to_json())
        manifest = payload["manifest"]
        assert manifest["dataset"]["content_hash"]
        assert "git_commit" in manifest
        assert manifest["judge_prompt_version"] >= 1

    def test_save_writes_json(self, tmp_path):
        path = self._report().save(tmp_path / "nested" / "report.json")
        assert path.exists()
        assert json.loads(path.read_text(encoding="utf-8"))["manifest"]

    def test_case_result_serialises_retrieval_detail(self):
        case_score = score_case(_case(), [_chunk(PAPER_A, 3)], k=5)
        result = CaseResult(
            case_id="c1",
            question="q",
            retrieved=[_chunk(PAPER_A, 3)],
            answer="a",
            retrieval=case_score,
        )
        payload = result.as_dict()
        assert payload["retrieval"]["hit"] is True
        assert payload["retrieved_chunks"][0]["page_number"] == 3


class TestReportComparison:
    def test_identical_datasets_compare(self):
        a = EvalReport(dataset=_dataset(_case()), config={"k": 5})
        b = EvalReport(dataset=_dataset(_case()), config={"k": 5})
        assert a.comparable_to(b)[0] is True

    def test_edited_dataset_blocks_comparison(self):
        """A delta against a different eval set would look like a finding."""
        a = EvalReport(dataset=_dataset(_case()), config={"k": 5})
        b = EvalReport(
            dataset=_dataset(_case(gold=[(PAPER_A, 9)])), config={"k": 5}
        )
        ok, reasons = a.comparable_to(b)
        assert ok is False
        assert any("dataset" in r for r in reasons)

    def test_changed_judge_prompt_version_blocks_comparison(self):
        a = EvalReport(dataset=_dataset(_case()), config={"k": 5}, judge_prompt_version=1)
        b = EvalReport(dataset=_dataset(_case()), config={"k": 5}, judge_prompt_version=2)
        assert a.comparable_to(b)[0] is False

    def test_changed_model_blocks_comparison(self):
        a = EvalReport(dataset=_dataset(_case()), config={}, models={"judge": "m1"})
        b = EvalReport(dataset=_dataset(_case()), config={}, models={"judge": "m2"})
        ok, reasons = a.comparable_to(b)
        assert ok is False
        assert any("model" in r for r in reasons)

    def test_config_change_is_reported_but_does_not_block(self):
        """Turning reranking on is the *point* of a comparison."""
        a = EvalReport(dataset=_dataset(_case()), config={"rerank": False})
        b = EvalReport(dataset=_dataset(_case()), config={"rerank": True})
        comparison = b.compare_to(a)
        assert comparison["comparable"] is True
        assert comparison["config_change"]["rerank"] == {
            "baseline": False,
            "candidate": True,
        }

    def test_generation_metrics_are_never_differenced(self):
        """Subtracting two noisy judge scores would invite over-reading."""
        a = EvalReport(
            dataset=_dataset(_case()),
            config={},
            generation=GenerationAggregate(means={"faithfulness": 0.4}),
        )
        b = EvalReport(
            dataset=_dataset(_case()),
            config={},
            generation=GenerationAggregate(means={"faithfulness": 0.9}),
        )
        comparison = b.compare_to(a)
        assert "retrieval_delta" not in comparison
        # Reported side by side, no delta.
        assert comparison["generation_comparison"]["faithfulness"] == {
            "baseline": 0.4,
            "candidate": 0.9,
        }


class TestRenderMarkdown:
    def _report(self) -> EvalReport:
        second = EvalCase(
            id="c2",
            question="q2",
            expected_pages=[GoldPage(paper_title="P", page_number=2, paper_id=PAPER_B)],
        )
        first_case, second_case = _case(), second
        hit = score_case(first_case, [_chunk(PAPER_A, 3)], k=5)
        miss = score_case(second_case, [_chunk(PAPER_A, 1)], k=5)
        return EvalReport(
            dataset=_dataset(first_case, second_case),
            config=EvalConfig(k=5).as_dict(),
            retrieval=aggregate([hit, miss], 5),
            results=[
                CaseResult(
                    case_id="c1", question="q1", retrieval=hit, retrieved=[_chunk(PAPER_A, 3)]
                ),
                CaseResult(
                    case_id="c2", question="q2", retrieval=miss, retrieved=[_chunk(PAPER_A, 1)]
                ),
            ],
        )

    def test_includes_provenance_and_metrics(self):
        markdown = render_markdown(self._report())
        assert "# RAG evaluation" in markdown
        assert "Dataset hash" in markdown
        assert "hit_rate" in markdown
        assert "Commit" in markdown

    def test_zero_cases_says_so_instead_of_showing_zeroes(self):
        """A 0.0 table would read as a terrible score, not no measurement."""
        report = EvalReport(
            dataset=_dataset(_case()),
            config=EvalConfig(k=5).as_dict(),
            retrieval=aggregate([], 5),
            results=[],
            unresolved_case_ids=["c1"],
        )
        markdown = render_markdown(report)
        assert "**No cases ran**" in markdown
        assert "hit_rate" not in markdown

    def test_lists_missed_cases(self):
        markdown = render_markdown(self._report())
        assert "## Misses" in markdown
        assert "c2" in markdown

    def test_suppresses_deltas_for_incomparable_runs(self):
        markdown = render_markdown(
            self._report(),
            {"comparable": False, "incomparable_reasons": ["dataset content hash differs"]},
        )
        assert "Not comparable" in markdown
        assert "Baseline" not in markdown

    def test_shows_deltas_for_comparable_runs(self):
        markdown = render_markdown(
            self._report(),
            {
                "comparable": True,
                "incomparable_reasons": [],
                "config_change": {"rerank": {"baseline": False, "candidate": True}},
                "retrieval_delta": {
                    "hit_rate": {"baseline": 0.0, "candidate": 1.0, "delta": 1.0}
                },
            },
        )
        assert "## Comparison with baseline" in markdown
        assert "+1.0" in markdown


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


class _FakeGenerated:
    def __init__(self, answer: str = "an answer"):
        self.answer = answer
        self.cited_chunks: list = []


class TestRunEvaluation:
    def _retriever(self, pages: list[int]):
        def _retrieve(question, user_id, config):
            return [_chunk(PAPER_A, page) for page in pages]

        return _retrieve

    def test_scores_retrieval_for_resolvable_cases(self):
        dataset = _dataset(_case("c1", gold=[(PAPER_A, 3)]))
        report = run_evaluation(
            dataset=dataset,
            user_id="user",
            config=EvalConfig(k=5, generate=False),
            retrieve_fn=self._retriever([3, 4]),
            library_titles={"Paper": PAPER_A},
        )
        assert report.retrieval.case_count == 1
        assert report.retrieval.hit_rate == pytest.approx(1.0)

    def test_unresolvable_cases_are_skipped_not_scored_as_misses(self):
        """Retrieval cannot find a document the library does not have.

        Counting these as failures would measure the dataset's fit to the
        library rather than the system's quality.
        """
        dataset = _dataset(
            _case("c1", gold=[(PAPER_A, 3)]),
            EvalCase(
                id="c2",
                question="q",
                expected_pages=[GoldPage(paper_title="Not In Library", page_number=1)],
            ),
        )
        report = run_evaluation(
            dataset=dataset,
            user_id="user",
            config=EvalConfig(k=5, generate=False),
            retrieve_fn=self._retriever([1, 2, 3]),
            library_titles={"Paper": PAPER_A},
        )
        assert len(report.results) == 1
        assert report.retrieval.case_count == 1
        assert report.unresolved_case_ids == ["c2"]

    def test_gold_is_resolved_by_title(self):
        dataset = _dataset(
            EvalCase(
                id="c1",
                question="q",
                expected_pages=[GoldPage(paper_title="Deep Learning", page_number=3)],
            )
        )
        report = run_evaluation(
            dataset=dataset,
            user_id="user",
            config=EvalConfig(k=5, generate=False),
            retrieve_fn=self._retriever([3]),
            library_titles={"Deep Learning": PAPER_A},
        )
        assert report.retrieval.hit_rate == pytest.approx(1.0)

    def test_retrieval_failure_is_contained_to_its_case(self):
        """One embedding timeout must not cost the other cases their scores."""
        dataset = _dataset(
            _case("c1"),
            EvalCase(
                id="c2",
                question="A different question",
                expected_pages=[GoldPage(paper_title="Paper", page_number=3, paper_id=PAPER_A)],
            ),
        )

        def _retrieve(question, user_id, config):
            if question == "A different question":
                raise RuntimeError("embedding timeout")
            return [_chunk(PAPER_A, 3)]

        report = run_evaluation(
            dataset=dataset,
            user_id="user",
            config=EvalConfig(k=5, generate=False),
            retrieve_fn=_retrieve,
            library_titles={"Paper": PAPER_A},
        )
        assert len(report.results) == 2
        failed = [r for r in report.results if r.error]
        scored = [r for r in report.results if r.retrieval is not None]
        assert len(failed) == 1 and "embedding timeout" in failed[0].error
        assert len(scored) == 1
        # The run still produced a usable aggregate from the case that worked.
        assert report.retrieval.case_count == 1

    def test_generation_and_judging_run_when_enabled(self):
        dataset = _dataset(_case("c1", characteristics=["cites a number"]))
        judged = []

        def _judge(metric, question, answer, chunks):
            judged.append(metric)
            return Judgement(metric=metric, score=1.0)

        report = run_evaluation(
            dataset=dataset,
            user_id="user",
            config=EvalConfig(k=5, generate=True, judge_metrics=("faithfulness",)),
            retrieve_fn=self._retriever([3]),
            generate_fn=lambda q, chunks: _FakeGenerated(),
            judge_fn=_judge,
            library_titles={"Paper": PAPER_A},
        )
        assert judged == ["faithfulness"]
        assert report.results[0].answer == "an answer"
        assert report.generation.means["faithfulness"] == pytest.approx(1.0)

    def test_no_generation_when_disabled(self):
        dataset = _dataset(_case("c1"))
        report = run_evaluation(
            dataset=dataset,
            user_id="user",
            config=EvalConfig(k=5, generate=False),
            retrieve_fn=self._retriever([3]),
            generate_fn=lambda q, chunks: pytest.fail("should not generate"),
            library_titles={"Paper": PAPER_A},
        )
        assert report.results[0].answer == ""
        assert report.generation.means == {}

    def test_case_without_characteristics_is_still_judged(self):
        """A blank expectations field must not silently drop a case.

        Faithfulness, context relevance and citation accuracy are judged
        from the excerpts and the answer alone, so refusing to measure a
        case because the dataset author left a field empty would turn an
        authoring gap into a missing metric.
        """
        dataset = _dataset(_case("c1", characteristics=[]))
        report = run_evaluation(
            dataset=dataset,
            user_id="user",
            config=EvalConfig(k=5, generate=True),
            retrieve_fn=self._retriever([3]),
            generate_fn=lambda q, chunks: _FakeGenerated(),
            judge_fn=lambda metric, *a: Judgement(metric=metric, score=1.0),
            library_titles={"Paper": PAPER_A},
        )
        assert [j.metric for j in report.results[0].judgements] == list(
            GENERATION_METRICS
        )
        assert report.generation.means["faithfulness"] == 1.0

    def test_expected_characteristics_are_recorded_for_review(self):
        """Human expectations reach the report, just not the judge."""
        dataset = _dataset(_case("c1", characteristics=["states 0.5"]))
        seen: list[str] = []

        def _judge(metric, question, answer, chunks):
            seen.append(answer)
            return Judgement(metric=metric, score=0.5)

        report = run_evaluation(
            dataset=dataset,
            user_id="user",
            config=EvalConfig(k=5, generate=True),
            retrieve_fn=self._retriever([3]),
            generate_fn=lambda q, chunks: _FakeGenerated(),
            judge_fn=_judge,
            library_titles={"Paper": PAPER_A},
        )
        result = report.results[0]
        assert result.expected_characteristics == ["states 0.5"]
        assert result.as_dict()["expected_characteristics"] == ["states 0.5"]
        # The judge is handed the question, answer and excerpts only.
        assert all("0.5" not in answer for answer in seen)

    def test_a_raising_judge_is_contained_to_its_case(self):
        """An injected judge that raises must not abort the run."""
        calls: list[str] = []

        def _judge(metric, *args):
            calls.append(metric)
            if metric == "faithfulness":
                raise RuntimeError("judge exploded")
            return Judgement(metric=metric, score=1.0)

        dataset = _dataset(_case("c1"))
        report = run_evaluation(
            dataset=dataset,
            user_id="user",
            config=EvalConfig(k=5, generate=True),
            retrieve_fn=self._retriever([3]),
            generate_fn=lambda q, chunks: _FakeGenerated(),
            judge_fn=_judge,
            library_titles={"Paper": PAPER_A},
        )
        judgements = {j.metric: j for j in report.results[0].judgements}
        assert judgements["faithfulness"].score is None
        assert "judge exploded" in judgements["faithfulness"].error
        # The remaining metrics still ran.
        assert len(calls) == len(GENERATION_METRICS)
        assert judgements["answer_relevance"].score == 1.0

    def test_models_manifest_records_generation_models(self):
        dataset = _dataset(_case("c1"))
        report = run_evaluation(
            dataset=dataset,
            user_id="user",
            config=EvalConfig(k=5, generate=True),
            retrieve_fn=self._retriever([3]),
            generate_fn=lambda q, chunks: _FakeGenerated(),
            judge_fn=lambda metric, *a: Judgement(metric=metric, score=1.0),
            library_titles={"Paper": PAPER_A},
        )
        assert set(report.models) == {"generator", "judge"}
        assert all(report.models.values())

    def test_retrieval_only_run_records_no_models(self):
        """No model was used, so claiming one would be false provenance."""
        report = run_evaluation(
            dataset=_dataset(_case("c1")),
            user_id="user",
            config=EvalConfig(k=5, generate=False),
            retrieve_fn=self._retriever([3]),
            library_titles={"Paper": PAPER_A},
        )
        assert report.models == {}

    def test_generation_failure_is_contained_to_its_case(self):
        def _generate(q, chunks):
            raise RuntimeError("no api key")

        dataset = _dataset(_case("c1"))
        report = run_evaluation(
            dataset=dataset,
            user_id="user",
            config=EvalConfig(k=5, generate=True),
            retrieve_fn=self._retriever([3]),
            generate_fn=_generate,
            library_titles={"Paper": PAPER_A},
        )
        result = report.results[0]
        assert "no api key" in result.error
        # Retrieval still scored: the failure was downstream of it.
        assert result.retrieval is not None
        assert result.retrieval.hit is True

    def test_rerank_flag_is_recorded_in_the_config(self):
        """The report has to say what was measured."""
        dataset = _dataset(_case())
        report = run_evaluation(
            dataset=dataset,
            user_id="user",
            config=EvalConfig(k=8, rerank=True, generate=False),
            retrieve_fn=self._retriever([3]),
            library_titles={"Paper": PAPER_A},
        )
        assert report.config["rerank"] is True
        assert report.config["k"] == 8


# ---------------------------------------------------------------------------
# The shipped example dataset
# ---------------------------------------------------------------------------


class TestExampleDataset:
    def test_ships_and_validates(self):
        from app.evaluation.cli import DEFAULT_DATASET

        assert DEFAULT_DATASET.exists(), "the example dataset should ship with the code"
        dataset = load_dataset(DEFAULT_DATASET)
        assert dataset.version
        assert len(dataset.cases) >= 5
        assert dataset.content_hash

    def test_every_case_has_gold_pages_and_a_question(self):
        from app.evaluation.cli import DEFAULT_DATASET

        for case in load_dataset(DEFAULT_DATASET).cases:
            assert case.question.strip()
            assert case.expected_pages
            assert all(p.page_number >= 1 for p in case.expected_pages)

    def test_asks_for_the_evidence_the_prd_names(self):
        """Every judged metric needs something to judge against."""
        from app.evaluation.cli import DEFAULT_DATASET

        dataset = load_dataset(DEFAULT_DATASET)
        assert any(c.expected_answer_characteristics for c in dataset.cases)

    def test_is_tagged_for_slicing(self):
        """Tagged cases are how a regression in exact-term retrieval gets seen."""
        from app.evaluation.cli import DEFAULT_DATASET

        tags = {tag for c in load_dataset(DEFAULT_DATASET).cases for tag in c.tags}
        assert "exact-term" in tags
        assert "numeric" in tags


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


class TestCLI:
    def test_rejects_a_missing_dataset(self, capsys):
        from app.evaluation.cli import main

        assert main(["--dataset", "nope.json", "--user-id", "u", "--no-generate"]) == 2
        assert "Dataset error" in capsys.readouterr().err

    def test_rejects_an_unknown_metric(self, tmp_path, capsys):
        from app.evaluation.cli import main

        path = tmp_path / "d.json"
        path.write_text(json.dumps(_raw_dataset()), encoding="utf-8")
        assert main(
            [
                "--dataset", str(path),
                "--user-id", "u",
                "--metrics", "vibes",
            ]
        ) == 2
        assert "Unknown metrics" in capsys.readouterr().err

    def test_rejects_a_malformed_dataset(self, tmp_path, capsys):
        from app.evaluation.cli import main

        path = tmp_path / "d.json"
        path.write_text("{", encoding="utf-8")
        assert main(["--dataset", str(path), "--user-id", "u"]) == 2
        assert "Dataset error" in capsys.readouterr().err

    def test_rerank_defaults_to_the_shipped_api_default(self):
        """The harness must measure the configuration users actually get.

        Search reranking is on by default in the API
        (``RERANK_SEARCH_DEFAULT``). If the harness defaulted it off, a
        plain run would score a configuration nobody deploys and the
        rerank A/B would silently compare nothing.
        """
        from app.core.config import get_settings

        assert EvalConfig().rerank is get_settings().RERANK_SEARCH_DEFAULT

    def test_cli_rerank_flags(self, tmp_path, monkeypatch):
        from app.evaluation import cli

        parser = cli.build_parser()
        assert parser.parse_args(["--user-id", "u"]).rerank is True
        assert parser.parse_args(["--user-id", "u", "--no-rerank"]).rerank is False
        assert parser.parse_args(["--user-id", "u", "--rerank"]).rerank is True

    def test_baseline_with_a_different_model_is_not_comparable(self, tmp_path, monkeypatch):
        """A model swap moves the judged metrics, so deltas are suppressed."""
        from app.evaluation import cli

        raw = _raw_dataset()
        dataset_file = tmp_path / "d.json"
        dataset_file.write_text(json.dumps(raw), encoding="utf-8")

        def _fake_run(dataset, user_id, config):
            return EvalReport(
                dataset=dataset,
                config=config.as_dict(),
                retrieval=aggregate([score_case(_case(), [_chunk(PAPER_A, 3)], k=5)], 5),
                results=[],
                models={"generator": "gemini-new"},
            )

        monkeypatch.setattr(cli, "run_evaluation", _fake_run)

        first = tmp_path / "first.json"
        cli.main(["--dataset", str(dataset_file), "--user-id", "u", "--out", str(first)])
        baseline = json.loads(first.read_text(encoding="utf-8"))
        baseline["manifest"]["models"] = {"generator": "gemini-old"}
        first.write_text(json.dumps(baseline), encoding="utf-8")

        md = tmp_path / "second.md"
        assert cli.main(
            [
                "--dataset", str(dataset_file),
                "--user-id", "u",
                "--baseline", str(first),
                "--markdown", str(md),
            ]
        ) == 0
        markdown = md.read_text(encoding="utf-8")
        assert "**Not comparable:**" in markdown
        assert "gemini-old" in markdown and "gemini-new" in markdown
        # The comparison section is present but shows no delta table.
        assert "## Comparison with baseline" in markdown
        assert "| Metric | Baseline | Candidate | Delta |" not in markdown

    def test_writes_reports_and_comparison(self, tmp_path, monkeypatch, capsys):
        from app.evaluation import cli

        dataset_file = tmp_path / "d.json"
        dataset_file.write_text(json.dumps(_raw_dataset()), encoding="utf-8")

        def _fake_run(dataset, user_id, config):
            return EvalReport(
                dataset=dataset,
                config=config.as_dict(),
                retrieval=aggregate([score_case(_case(), [_chunk(PAPER_A, 3)], k=5)], 5),
                results=[],
            )

        monkeypatch.setattr(cli, "run_evaluation", _fake_run)

        out = tmp_path / "run.json"
        md = tmp_path / "run.md"
        assert cli.main(
            [
                "--dataset", str(dataset_file),
                "--user-id", "u",
                "--out", str(out),
                "--markdown", str(md),
            ]
        ) == 0
        assert out.exists()
        assert json.loads(out.read_text(encoding="utf-8"))["retrieval"]["k"] == 5
        assert "# RAG evaluation" in md.read_text(encoding="utf-8")
        capsys.readouterr()

    def test_baseline_comparison_writes_a_report(self, tmp_path, monkeypatch, capsys):
        from app.evaluation import cli

        dataset_file = tmp_path / "d.json"
        dataset_file.write_text(json.dumps(_raw_dataset()), encoding="utf-8")

        def _fake_run(dataset, user_id, config):
            return EvalReport(
                dataset=dataset,
                config=config.as_dict(),
                retrieval=aggregate([score_case(_case(), [_chunk(PAPER_A, 3)], k=5)], 5),
                results=[],
            )

        monkeypatch.setattr(cli, "run_evaluation", _fake_run)

        first = tmp_path / "first.json"
        cli.main(["--dataset", str(dataset_file), "--user-id", "u", "--out", str(first)])
        capsys.readouterr()

        md = tmp_path / "second.md"
        assert cli.main(
            [
                "--dataset", str(dataset_file),
                "--user-id", "u",
                "--rerank",
                "--baseline", str(first),
                "--markdown", str(md),
            ]
        ) == 0
        markdown = md.read_text(encoding="utf-8")
        assert "## Comparison with baseline" in markdown
        assert "rerank" in markdown

    def test_handles_non_ascii_questions_and_titles(self, tmp_path, monkeypatch):
        """Paper titles and questions are not ASCII, and the report echoes them.

        Printing such a report to a stock Windows console (cp1252) raises
        UnicodeEncodeError, which would surface as a failed run even though
        the reports were already written.
        """
        from app.evaluation import cli

        raw = _raw_dataset()
        raw["cases"][0]["question"] = "Wie groß ist der Kompressionsfaktor θ?"
        raw["cases"][0]["expected_pages"][0]["paper_title"] = "Révision – Größe"
        dataset_file = tmp_path / "d.json"
        dataset_file.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

        # A cp1252 stream that rejects anything outside its charset, as on
        # a default Windows console. It has no reconfigure, so this also
        # covers the fallback path in _echo().
        class _NarrowStream:
            encoding = "cp1252"

            def write(self, text: str) -> int:
                text.encode("cp1252")
                return len(text)

            def flush(self) -> None:
                pass

        monkeypatch.setattr(sys, "stdout", _NarrowStream())

        def _fake_run(dataset, user_id, config):
            resolved = resolve_gold(dataset, {"Révision – Größe": PAPER_A})
            case = resolved.cases[0]
            hit = score_case(case, [_chunk(PAPER_A, 1)], k=config.k)
            return EvalReport(
                dataset=resolved,
                config=config.as_dict(),
                retrieval=aggregate([hit], config.k),
                results=[
                    CaseResult(
                        case_id=case.id,
                        question=case.question,
                        retrieval=hit,
                        retrieved=[_chunk(PAPER_A, 1)],
                    )
                ],
            )

        monkeypatch.setattr(cli, "run_evaluation", _fake_run)

        out = tmp_path / "run.json"
        md = tmp_path / "run.md"
        assert cli.main(
            [
                "--dataset", str(dataset_file),
                "--user-id", "u",
                "--no-generate",
                "--out", str(out),
                "--markdown", str(md),
            ]
        ) == 0
        assert out.exists() and md.exists()

    def test_echo_degrades_unencodable_characters(self, monkeypatch):
        """A narrow console must lose characters, not abort the run."""
        from app.evaluation import cli

        written: list[str] = []

        class _NarrowStream:
            encoding = "cp1252"

            def write(self, text: str) -> int:
                text.encode("cp1252")
                written.append(text)
                return len(text)

            def flush(self) -> None:
                pass

        monkeypatch.setattr(cli.sys, "stdout", _NarrowStream())
        cli._echo("theta θ and an arrow →")
        printed = "".join(written)
        assert printed.startswith("theta") and printed.endswith("\n")
        assert "θ" not in printed and "→" not in printed


# ---------------------------------------------------------------------------
# Test helpers for patching
# ---------------------------------------------------------------------------


import contextlib  # noqa: E402
from unittest.mock import MagicMock, patch  # noqa: E402


@contextlib.contextmanager
def patch_settings(api_key: str):
    """Force a GEMINI_API_KEY for the duration of the block."""
    settings = MagicMock()
    settings.GEMINI_API_KEY = api_key
    settings.GEMINI_GENERATION_MODEL = "test-model"
    with patch("app.evaluation.judge.get_settings", return_value=settings):
        yield


@contextlib.contextmanager
def patch_genai_response(text: str):
    """Make the judge SDK call return *text*."""
    client = MagicMock()
    client.models.generate_content.return_value = MagicMock(text=text)
    with patch("app.evaluation.judge.genai.Client", return_value=client):
        yield client


@contextlib.contextmanager
def patch_genai_failure(exc: Exception):
    client = MagicMock()
    client.models.generate_content.side_effect = exc
    with patch("app.evaluation.judge.genai.Client", return_value=client):
        yield client
