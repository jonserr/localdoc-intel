"""A malformed judge verdict is unjudged, never a perfect score."""

import math

import pytest

from evaluations.judging import (
    AnswerJudgeError,
    AnswerQualityResult,
    judge_answer_quality,
    normalize_answer_quality_result,
)


class StubJudge:
    """Return a fixed payload in place of a local model verdict."""

    model = "stub-judge"

    def __init__(self, payload):
        self.payload = payload

    def judge(self, question, answer, context, expected_terms):
        return self.payload


# "NaN" and "Infinity" survive float() and then survive clamping:
# min(1.0, nan) returns 1.0. True is an int subclass and clamps to 1.0.
INVALID_SCORES = [True, False, "NaN", "Infinity", "-Infinity", float("nan")]


@pytest.mark.parametrize("score", INVALID_SCORES)
def test_invalid_scores_are_rejected(score):
    with pytest.raises(AnswerJudgeError):
        normalize_answer_quality_result({"score": score})


@pytest.mark.parametrize("score", INVALID_SCORES)
def test_invalid_scores_are_recorded_as_unjudged(score):
    result = judge_answer_quality(
        question="Q?",
        answer="A [1]",
        context="evidence",
        expected_terms=[],
        provider=StubJudge({"score": score, "rationale": "nonsense"}),
    )

    assert result.score is None
    assert result.error


@pytest.mark.parametrize("missing", [{}, {"score": None}, {"score": "high"}])
def test_missing_or_unparsable_scores_are_rejected(missing):
    with pytest.raises(AnswerJudgeError):
        normalize_answer_quality_result(missing)


@pytest.mark.parametrize(
    "raw,expected", [(0.75, 0.75), ("0.5", 0.5), (1.4, 1.0), (-0.2, 0.0)]
)
def test_finite_scores_are_kept_and_clamped(raw, expected):
    result = normalize_answer_quality_result({"score": raw, "rationale": "ok"})

    assert result.score == pytest.approx(expected)
    assert math.isfinite(result.score)
    assert result.rationale == "ok"


def test_provider_result_passes_through_unchanged():
    verdict = AnswerQualityResult(score=0.4, rationale="already normalized")

    assert normalize_answer_quality_result(verdict) is verdict
