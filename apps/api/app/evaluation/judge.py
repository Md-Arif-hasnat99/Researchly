"""LLM-judged generation quality metrics (FR-16).

FR-16 asks for four generation metrics: faithfulness, answer relevance,
context relevance, and citation accuracy. None of them can be computed
deterministically from a string comparison, so all four are judged by a
model. That is a real limitation, not a formality, and it shapes the
design here:

**One call per metric, not one call for all four.** Faithfulness asks
"is every claim here supported by the context?" while relevance asks
"does this answer the question asked?". A single call asked for both
returns one blended number that moves with either, which tells you
nothing about which one changed. Separate calls also isolate failures: a
malformed reply for faithfulness costs one metric, not four.

**A failed judgement is unscored, not zero.** If the model returns
unreadable JSON, the metric is recorded as ``None`` and excluded from
the mean, with the count of unscored judgements reported next to the
score. Scoring a judge failure as 0.0 would drag the mean down and make
a judge outage look like a quality regression.

**The rubric is in the prompt, not in the interpretation.** Each metric
ships explicit anchors for what each score means, so a 0.5 is a
described judgement rather than a vibe. The scale is 0.0-1.0 because
these are comparative judgements, not measurements; a judge is not a
calibrated instrument and pretending otherwise would overstate what one
model call can tell you.

The judge never sees the gold pages, only what retrieval returned and
what the generator wrote. Letting it see the labels would let it grade
against the answer key rather than against the system's behaviour.
"""

import json
import logging
from dataclasses import dataclass

import google.genai as genai
import google.genai.types as genai_types

from app.core.config import get_settings
from app.schemas.search import SearchResultChunk

logger = logging.getLogger("researchly")


# Bumped whenever a rubric or prompt changes in a way that would move
# scores. Recorded in the report so two runs' judge numbers are only
# compared when this matches.
JUDGE_PROMPT_VERSION = 1

JUDGE_TEMPERATURE = 0.0
"""Greedy decoding. The only meaningful determinism lever for a judge."""


# ---------------------------------------------------------------------------
# Metric definitions
# ---------------------------------------------------------------------------

_SCALE = (
    "Score on a 0.0 to 1.0 scale using these anchors:\n"
    "- 1.0 — fully satisfies the criterion.\n"
    "- 0.5 — partially satisfies it, or satisfies it only for part of the answer.\n"
    "- 0.0 — does not satisfy it at all."
)

METRIC_RUBRICS: dict[str, str] = {
    "faithfulness": (
        "Faithfulness: is every claim in the answer actually supported by the "
        "supplied source excerpts?\n"
        "Check each factual claim against the excerpts. A claim that goes "
        "beyond what the excerpts state is unfaithful, even if it is true in "
        "the real world — the excerpts are the only permitted evidence.\n"
        "The excerpts may simply not contain the answer; that is a retrieval "
        "problem, not unfaithfulness, so do not penalise a missing excerpt "
        "here.\n"
        + _SCALE
    ),
    "answer_relevance": (
        "Answer relevance: does the answer address the question that was "
        "asked?\n"
        "A relevant answer responds to what was actually asked, at the right "
        "level of detail. Padding, digressions, and answers to a different "
        "question all score low. An honest 'I could not find this in the "
        "papers' is fully relevant when the excerpts genuinely do not cover "
        "the question, and must not be penalised.\n"
        + _SCALE
    ),
    "context_relevance": (
        "Context relevance: how much of the supplied source material was "
        "actually useful for answering this question?\n"
        "Judge the excerpts, not the answer. Irrelevant padding lowers the "
        "score even when the top excerpt was perfect; excerpts from the "
        "wrong paper or wrong section count against it.\n"
        + _SCALE
    ),
    "citation_accuracy": (
        "Citation accuracy: do the numbered citations in the answer point to "
        "excerpts that support the claims they are attached to?\n"
        "Each claim carries a marker like [1] referring to a numbered excerpt. "
        "For every marker, check that the excerpt it points to supports that "
        "specific claim. A citation pointing to a real but unrelated excerpt "
        "is inaccurate, and so is a claim with no citation at all when the "
        "excerpts clearly support it.\n"
        + _SCALE
    ),
}

GENERATION_METRICS: tuple[str, ...] = (
    "faithfulness",
    "answer_relevance",
    "context_relevance",
    "citation_accuracy",
)


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


@dataclass
class Judgement:
    """One judged metric for one case."""

    metric: str
    score: float | None
    """0.0-1.0, or None when the judge could not be read.

    None means *no opinion*, never *zero quality*.
    """

    reason: str = ""
    error: str | None = None

    @property
    def scored(self) -> bool:
        return self.score is not None

    def as_dict(self) -> dict:
        return {
            "metric": self.metric,
            "score": None if self.score is None else round(self.score, 4),
            "reason": self.reason,
            "error": self.error,
        }


# ---------------------------------------------------------------------------
# Prompting
# ---------------------------------------------------------------------------


def _excerpt(chunk: SearchResultChunk) -> str:
    """Render one context chunk, numbered to match the answer's markers."""
    content = " ".join(chunk.content.split())
    if len(content) > 1200:
        content = content[:1200].rstrip() + "…"
    location = f"p{chunk.page_number}"
    if chunk.section:
        location += f", {chunk.section}"
    return f"[{location}] {content}"


def _build_prompt(
    metric: str,
    question: str,
    answer: str,
    chunks: list[SearchResultChunk],
) -> str:
    numbered = "\n\n".join(
        f"Excerpt {index}: {_excerpt(chunk)}"
        for index, chunk in enumerate(chunks, start=1)
    )
    return (
        f"{METRIC_RUBRICS[metric]}\n\n"
        f"---\n\n"
        f"Question:\n{question}\n\n"
        f"Source excerpts:\n\n{numbered}\n\n"
        f"Answer to grade:\n{answer}\n\n"
        f"---\n"
        f'Return a JSON object: {{"score": <float 0.0-1.0>, "reason": '
        f'"<one or two sentences citing the specific text you relied on>"}}.'
    )


def _response_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "score": {
                "type": "number",
                "description": "0.0-1.0 against the rubric anchors above.",
            },
            "reason": {
                "type": "string",
                "description": "One or two sentences naming the evidence used.",
            },
        },
        "required": ["score", "reason"],
        "propertyOrdering": ["score", "reason"],
    }


# ---------------------------------------------------------------------------
# Judging
# ---------------------------------------------------------------------------


def _parse_judgement(metric: str, raw_text: str) -> Judgement:
    """Read a judge reply, clamping the score into range.

    Out-of-range and non-numeric scores become unscored rather than being
    clamped silently: a model returning 7.0 has not made a judgement on
    the stated scale, and quietly treating it as 1.0 would fabricate a
    perfect result.
    """
    try:
        payload = json.loads(raw_text)
    except (TypeError, ValueError):
        return Judgement(
            metric=metric,
            score=None,
            error="judge reply was not valid JSON",
        )

    if not isinstance(payload, dict) or "score" not in payload:
        return Judgement(metric=metric, score=None, error="judge reply had no score")

    raw_score = payload["score"]
    if isinstance(raw_score, bool) or not isinstance(raw_score, (int, float)):
        return Judgement(
            metric=metric,
            score=None,
            error=f"judge returned a non-numeric score: {raw_score!r}",
        )

    score = float(raw_score)
    if not 0.0 <= score <= 1.0:
        return Judgement(
            metric=metric,
            score=None,
            error=f"judge score {score} is outside the 0.0-1.0 scale",
        )

    reason = payload.get("reason")
    return Judgement(
        metric=metric,
        score=score,
        reason=reason if isinstance(reason, str) else "",
    )


def judge_metric(
    metric: str,
    question: str,
    answer: str,
    chunks: list[SearchResultChunk],
) -> Judgement:
    """Judge one metric for one case.

    Never raises: a missing API key, a model error, or an unreadable
    reply all come back as an unscored :class:`Judgement` so a single
    failure cannot abort a run that has already paid for earlier cases.

    Raises:
        ValueError: if *metric* is not one of :data:`GENERATION_METRICS`.
    """
    if metric not in METRIC_RUBRICS:
        raise ValueError(
            f"Unknown metric {metric!r}. Known metrics: {sorted(METRIC_RUBRICS)}"
        )

    settings = get_settings()
    if not settings.GEMINI_API_KEY:
        return Judgement(
            metric=metric,
            score=None,
            error="GEMINI_API_KEY is not configured",
        )

    if not answer.strip():
        # Nothing to grade. Reported as unscored rather than 0.0: an empty
        # answer is a generation outcome, and grading it against
        # faithfulness would credit a distinction the judge cannot make.
        return Judgement(
            metric=metric,
            score=None,
            error="no answer to judge",
        )

    prompt = _build_prompt(metric, question, answer, chunks)
    client = genai.Client(api_key=settings.GEMINI_API_KEY)

    try:
        response = client.models.generate_content(
            model=settings.GEMINI_GENERATION_MODEL,
            contents=[
                genai_types.Content(
                    role="user",
                    parts=[genai_types.Part(text=prompt)],
                )
            ],
            config=genai_types.GenerateContentConfig(
                temperature=JUDGE_TEMPERATURE,
                max_output_tokens=1024,
                response_mime_type="application/json",
                response_schema=_response_schema(),
            ),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Judge call failed for %s: %s", metric, exc)
        return Judgement(metric=metric, score=None, error=f"judge call failed: {exc}")

    judgement = _parse_judgement(metric, response.text or "")
    if not judgement.scored:
        logger.warning("Judgement unscored for %s: %s", metric, judgement.error)
    return judgement


def judge_all(
    metrics: tuple[str, ...],
    question: str,
    answer: str,
    chunks: list[SearchResultChunk],
) -> list[Judgement]:
    """Judge several metrics for one case."""
    return [judge_metric(metric, question, answer, chunks) for metric in metrics]


def average_scores(judgements: list[Judgement]) -> float | None:
    """Mean of the scored judgements, or None when nothing was scored."""
    scored = [j.score for j in judgements if j.score is not None]
    if not scored:
        return None
    return sum(scored) / len(scored)
