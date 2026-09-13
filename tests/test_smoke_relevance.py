"""Smoke assertions distinguish lexical emptiness from dense score filtering."""

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location(
    "smoke_test", Path(__file__).resolve().parents[1] / "scripts" / "smoke_test.py"
)
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


def response(strategy="vector", score=0.3, source="vector", rerank=False):
    return {
        "citations": [{"score": score, "retrieval_source": source}],
        "metadata": {
            "retrieval_strategy": strategy,
            "rerank": rerank,
            "answer_mode": "extractive",
        },
    }


@pytest.mark.parametrize("floor,score", [(0.0, 0.3), (0.01, 0.3), (0.37, 0.37)])
def test_dense_results_at_or_above_floor_are_allowed(floor, score):
    smoke.validate_unrelated_response(
        response(score=score), vector_search_on=True, vector_floor=floor
    )


@pytest.mark.parametrize(
    "changes",
    [{"score": 0.2}, {"score": float("nan")}, {"source": "hybrid"}, {"rerank": True}],
)
def test_invalid_dense_score_evidence_fails(changes):
    with pytest.raises(smoke.SmokeFailure):
        smoke.validate_unrelated_response(
            response(**changes), vector_search_on=True, vector_floor=0.3
        )


def test_lexical_fallback_still_requires_empty_results():
    with pytest.raises(smoke.SmokeFailure, match="lexical path"):
        smoke.validate_unrelated_response(
            response(strategy="bm25"), vector_search_on=True, vector_floor=0.0
        )


@pytest.mark.parametrize("enabled", [True, False])
def test_empty_fallback_requires_no_results_answer(enabled):
    payload = {
        "citations": [],
        "metadata": {"retrieval_strategy": "bm25", "answer_mode": "no_results"},
    }
    smoke.validate_unrelated_response(
        payload, vector_search_on=enabled, vector_floor=0.0
    )
    payload["metadata"]["answer_mode"] = "generated"
    with pytest.raises(smoke.SmokeFailure, match="no_results"):
        smoke.validate_unrelated_response(
            payload, vector_search_on=enabled, vector_floor=0.0
        )


def test_main_requests_unreranked_vector_scores_and_accepts_positive_floor(monkeypatch):
    monkeypatch.setattr(smoke.uuid, "uuid4", lambda: SimpleNamespace(hex="12345678"))
    monkeypatch.setattr(sys, "argv", ["smoke_test.py"])
    replies = [
        {"status": "ok", "database": "ok"},
        {
            "documents": [
                {
                    "document": {
                        "id": 1,
                        "status": "indexed",
                        "metadata": {"offset_basis": "source_bytes"},
                    }
                }
            ]
        },
        [
            {
                "start_line": 1,
                "byte_start": 0,
                "token_count": 3,
                "text": "reconciliation",
            }
        ],
        {"citations": [{"document": "smoke-12345678.txt"}]},
        {"features": {"vector_search": "enabled"}, "vector_min_score": 0.01},
        {
            **response(),
            "metadata": {**response()["metadata"], "citation_status": "extractive"},
        },
    ]

    def request(url, **kwargs):
        if kwargs.get(
            "content_type", "application/json"
        ) == "application/json" and kwargs.get("body"):
            payload = json.loads(kwargs["body"])
            if payload["question"] == smoke.UNRELATED_QUESTION:
                assert payload["retrieval_mode"] == "vector"
                assert payload["rerank"] is False
        return replies.pop(0)

    monkeypatch.setattr(smoke, "request_json", request)
    assert smoke.main() == 0
    assert replies == []
