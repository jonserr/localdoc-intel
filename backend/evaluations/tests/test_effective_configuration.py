"""Effective settings are captured at execution, not reconstructed at display."""

import pytest

from evaluations.harness import QuestionResult, run_evaluation
from evaluations.runs import record_evaluation_run
from evaluations.serializers import EvaluationRunSerializer


@pytest.mark.django_db
@pytest.mark.parametrize("floor", [0.0, 0.37])
@pytest.mark.parametrize("retrieval_only", [True, False])
def test_run_persists_and_serializes_effective_configuration(
    settings, monkeypatch, floor, retrieval_only
):
    settings.VECTOR_MIN_SCORE = floor
    settings.VECTOR_SEARCH_ENABLED = True
    settings.ANSWER_GENERATION_ENABLED = False
    monkeypatch.setattr(
        "evaluations.harness.evaluate_question",
        lambda *args, **kwargs: QuestionResult(
            question="fixture",
            expected_document="",
            hit=False,
            reciprocal_rank=0,
            term_coverage=None,
            latency_ms=0,
            retrieval_strategy="vector",
        ),
    )
    metrics = run_evaluation([{"question": "fixture"}], retrieval_only=retrieval_only)
    # A later settings change must not overwrite what the run actually used.
    settings.VECTOR_MIN_SCORE = 0.99
    settings.VECTOR_SEARCH_ENABLED = False
    saved = record_evaluation_run("Synthetic configuration test", metrics)
    saved.refresh_from_db()
    config = EvaluationRunSerializer(saved).data["config"]
    assert config == {
        "vector_min_score": floor,
        "vector_search_enabled": True,
        "answer_generation_enabled": False,
        "retrieval_only": retrieval_only,
        "hybrid_fusion": "rrf",
        "rrf_rank_constant": 60,
        "retrieval_strategy_counts": {"vector": 1},
    }
