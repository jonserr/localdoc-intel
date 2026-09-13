from rest_framework import serializers

from .models import EvaluationRun


class EvaluationRunRequestSerializer(serializers.Serializer):
    name = serializers.CharField(default="Manual evaluation", max_length=160)
    top_k = serializers.IntegerField(min_value=1, max_value=20, default=5)
    mode = serializers.ChoiceField(
        choices=["vector", "hybrid", "metadata-filtered"],
        default="hybrid",
    )
    rerank = serializers.BooleanField(default=True)


class EvaluationRunSerializer(serializers.ModelSerializer):
    class Meta:
        model = EvaluationRun
        fields = [
            "id",
            "name",
            "recall_at_k",
            "mean_reciprocal_rank",
            "expected_term_coverage",
            "groundedness_score",
            "answer_quality_score",
            "judged_answer_count",
            "answer_judge_model",
            "average_latency_ms",
            "question_count",
            "labeled_question_count",
            "coverage_question_count",
            "no_results_precision",
            "no_results_question_count",
            "retrieval_mode",
            "retrieval_strategy",
            "fallback_reason",
            "top_k",
            "rerank",
            "embedding_model",
            "llm_model",
            "corpus_hash",
            "corpus_document_count",
            "chunk_hash",
            "corpus_chunk_count",
            "question_set_hash",
            "question_set_path",
            "revision",
            "config",
            "created_at",
        ]
