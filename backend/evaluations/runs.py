"""Persist evaluation metrics together with their reproducibility context."""

from __future__ import annotations

from .harness import EvaluationIdentity, EvaluationMetrics
from .models import EvaluationRun


def record_evaluation_run(
    name: str,
    metrics: EvaluationMetrics,
    identity: EvaluationIdentity | None = None,
) -> EvaluationRun:
    identity_fields = (
        {
            "embedding_model": identity.embedding_model,
            "llm_model": identity.llm_model,
            "corpus_hash": identity.corpus_hash,
            "corpus_document_count": identity.corpus_document_count,
            "chunk_hash": identity.chunk_hash,
            "corpus_chunk_count": identity.corpus_chunk_count,
            "question_set_hash": identity.question_set_hash,
            "question_set_path": identity.question_set_path,
            "revision": identity.revision,
        }
        if identity is not None
        else {}
    )
    return EvaluationRun.objects.create(
        name=name,
        recall_at_k=metrics.recall_at_k,
        mean_reciprocal_rank=metrics.mean_reciprocal_rank,
        expected_term_coverage=metrics.expected_term_coverage,
        groundedness_score=metrics.groundedness_score,
        answer_quality_score=metrics.answer_quality_score,
        judged_answer_count=metrics.judged_answer_count,
        answer_judge_model=metrics.answer_judge_model,
        average_latency_ms=metrics.average_latency_ms,
        question_count=metrics.question_count,
        labeled_question_count=metrics.labeled_question_count,
        coverage_question_count=metrics.coverage_question_count,
        no_results_precision=metrics.no_results_precision,
        no_results_question_count=metrics.no_results_question_count,
        retrieval_mode=metrics.requested_mode,
        retrieval_strategy=metrics.retrieval_strategy,
        fallback_reason=metrics.fallback_reason,
        top_k=metrics.top_k,
        rerank=metrics.rerank,
        config={
            **metrics.effective_config,
            "retrieval_strategy_counts": metrics.retrieval_strategy_counts,
        },
        **identity_fields,
    )
