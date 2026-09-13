"""Question sets are type-checked, and errors name the offending row."""

import json

import pytest

from evaluations.harness import EvaluationInputError, load_questions

VALID_ROW = {
    "question": "What should be validated before deployment?",
    "expected_document": "deployment_guide.md",
    "expected_terms": ["migrations"],
    "expect_no_results": False,
    "kind": "relevant",
}


def write_questions(tmp_path, rows):
    path = tmp_path / "questions.json"
    path.write_text(json.dumps(rows), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    "row,fragment",
    [
        (None, "must be a JSON object"),
        ("just a string", "must be a JSON object"),
        ({"question": 42}, "non-empty 'question' string"),
        ({"question": "   "}, "non-empty 'question' string"),
        ({}, "non-empty 'question' string"),
        ({**VALID_ROW, "expect_no_results": "false"}, "'expect_no_results'"),
        ({**VALID_ROW, "expect_no_results": 1}, "'expect_no_results'"),
        ({**VALID_ROW, "expected_document": 7}, "'expected_document'"),
        ({**VALID_ROW, "kind": ["relevant"]}, "'kind'"),
        ({**VALID_ROW, "expected_terms": "migrations"}, "'expected_terms'"),
        ({**VALID_ROW, "expected_terms": ["ok", 3]}, "'expected_terms'"),
    ],
)
def test_malformed_rows_are_rejected(tmp_path, row, fragment):
    path = write_questions(tmp_path, [VALID_ROW, row])

    with pytest.raises(EvaluationInputError) as failure:
        load_questions(path)

    message = str(failure.value)
    assert fragment in message
    # Row numbers are 1-based so they match what an editor shows.
    assert "Question 2" in message


def test_valid_rows_load_unchanged(tmp_path):
    rows = [VALID_ROW, {"question": "Only a question"}]

    assert load_questions(write_questions(tmp_path, rows)) == rows


def test_empty_array_is_rejected(tmp_path):
    with pytest.raises(EvaluationInputError, match="non-empty JSON array"):
        load_questions(write_questions(tmp_path, []))
