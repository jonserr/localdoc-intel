from django.test import override_settings

from evaluations.judging import build_judge_request


@override_settings(EVAL_JUDGE_MAX_CONTEXT_CHARS=50)
def test_build_judge_request_truncates_long_context():
    request = build_judge_request(
        question="Q?",
        answer="A [1]",
        context="x" * 500,
        expected_terms=["term"],
    )

    assert "[evidence truncated]" in request
    assert "x" * 51 not in request


@override_settings(EVAL_JUDGE_MAX_CONTEXT_CHARS=4000)
def test_build_judge_request_keeps_short_context():
    request = build_judge_request(
        question="Q?",
        answer="A [1]",
        context="short evidence",
        expected_terms=[],
    )

    assert "short evidence" in request
    assert "[evidence truncated]" not in request


def test_parse_judge_json_salvages_json_wrapped_in_prose():
    from evaluations.judging import parse_judge_json

    payload = parse_judge_json(
        'Here is my evaluation: {"score": 0.75, "rationale": "Good grounding."} Hope that helps!'
    )

    assert payload["score"] == 0.75
    assert payload["rationale"] == "Good grounding."


def test_parse_judge_json_salvages_truncated_output():
    from evaluations.judging import parse_judge_json

    payload = parse_judge_json(
        '{"score": 0.6, "rationale": "The answer was cut off mid-sen'
    )

    assert payload["score"] == 0.6
    assert "truncated" in payload["rationale"]


def test_parse_judge_json_still_rejects_garbage():
    import pytest as _pytest

    from evaluations.judging import AnswerJudgeError, parse_judge_json

    with _pytest.raises(AnswerJudgeError):
        parse_judge_json("I refuse to answer in JSON.")
