from rest_framework import generics, status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from .harness import (
    EvaluationInputError,
    default_questions_path,
    evaluation_identity,
    load_questions,
    run_evaluation,
)
from .models import EvaluationRun
from .runs import record_evaluation_run
from .serializers import EvaluationRunRequestSerializer, EvaluationRunSerializer


class EvaluationRunListView(generics.ListAPIView):
    queryset = EvaluationRun.objects.all()
    serializer_class = EvaluationRunSerializer


class RunEvaluationView(APIView):
    def post(self, request):
        serializer = EvaluationRunRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            questions_path = default_questions_path()
            questions = load_questions(questions_path)
            identity = evaluation_identity(questions, questions_path)
            metrics = run_evaluation(
                questions,
                top_k=serializer.validated_data["top_k"],
                mode=serializer.validated_data["mode"],
                rerank=serializer.validated_data["rerank"],
            )
        except EvaluationInputError as exc:
            raise ValidationError({"questions": str(exc)}) from exc

        run = record_evaluation_run(
            serializer.validated_data["name"], metrics, identity
        )
        return Response(
            EvaluationRunSerializer(run).data, status=status.HTTP_201_CREATED
        )
