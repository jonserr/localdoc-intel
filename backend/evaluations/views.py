from rest_framework import generics, status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from .harness import (
    EvaluationInputError,
    default_questions_path,
    load_questions,
    run_evaluation,
)
from .models import EvaluationRun
from .serializers import EvaluationRunRequestSerializer, EvaluationRunSerializer


class EvaluationRunListView(generics.ListAPIView):
    queryset = EvaluationRun.objects.all()
    serializer_class = EvaluationRunSerializer


class RunEvaluationView(APIView):
    def post(self, request):
        serializer = EvaluationRunRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            questions = load_questions(default_questions_path())
            metrics = run_evaluation(
                questions,
                top_k=serializer.validated_data["top_k"],
                mode=serializer.validated_data["mode"],
                rerank=serializer.validated_data["rerank"],
            )
        except EvaluationInputError as exc:
            raise ValidationError({"questions": str(exc)}) from exc

        run = EvaluationRun.objects.create(
            name=serializer.validated_data["name"],
            recall_at_k=metrics.recall_at_k,
            mean_reciprocal_rank=metrics.mean_reciprocal_rank,
            citation_coverage=metrics.citation_coverage,
            groundedness_score=metrics.groundedness_score,
            answer_quality_score=metrics.answer_quality_score,
            judged_answer_count=metrics.judged_answer_count,
            answer_judge_model=metrics.answer_judge_model,
            average_latency_ms=metrics.average_latency_ms,
            question_count=metrics.question_count,
            labeled_question_count=getattr(metrics, "labeled_question_count", 0),
            coverage_question_count=getattr(metrics, "coverage_question_count", 0),
        )
        return Response(
            EvaluationRunSerializer(run).data, status=status.HTTP_201_CREATED
        )
