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
            "citation_coverage",
            "groundedness_score",
            "answer_quality_score",
            "judged_answer_count",
            "answer_judge_model",
            "average_latency_ms",
            "question_count",
            "labeled_question_count",
            "coverage_question_count",
            "created_at",
        ]
