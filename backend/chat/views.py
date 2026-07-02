import time

from django.conf import settings
from rest_framework import generics, status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView
from retrieval.services import retrieve_chunks

from .generation import generate_answer
from .models import ChatQuery
from .serializers import ChatQueryRequestSerializer, ChatQuerySerializer


class ChatQueryView(APIView):
    def post(self, request):
        serializer = ChatQueryRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        started = time.perf_counter()
        retrieved = retrieve_chunks(
            question=data["question"],
            collection=data.get("collection") or None,
            top_k=data["top_k"],
            mode=data["retrieval_mode"],
            rerank=data["rerank"],
        )
        retrieval_latency_ms = int((time.perf_counter() - started) * 1000)

        citations = [
            {
                "source_number": number,
                "document": item.chunk.document.title,
                "document_id": item.chunk.document_id,
                "chunk_id": item.chunk.id,
                "page": item.chunk.page,
                "start_line": item.chunk.start_line,
                "end_line": item.chunk.end_line,
                "score": item.score,
                "retrieval_source": item.source,
                "text_preview": item.chunk.text[:240],
            }
            for number, item in enumerate(retrieved, start=1)
        ]

        generation = generate_answer(data["question"], retrieved)
        latency_ms = int((time.perf_counter() - started) * 1000)

        query = ChatQuery.objects.create(
            question=data["question"],
            answer=generation.answer,
            retrieval_mode=data["retrieval_mode"],
            retrieval_top_k=data["top_k"],
            collection=data.get("collection", ""),
            citation_count=len(citations),
            latency_ms=latency_ms,
        )

        return Response(
            {
                "id": query.id,
                "answer": generation.answer,
                "citations": citations,
                "metadata": {
                    "retrieval_mode": data["retrieval_mode"],
                    "retrieval_top_k": data["top_k"],
                    "embedding_model": settings.EMBEDDING_MODEL,
                    "llm_model": settings.LLM_MODEL,
                    "answer_mode": generation.mode,
                    "generation_error": generation.error,
                    "retrieval_latency_ms": retrieval_latency_ms,
                    "latency_ms": latency_ms,
                    "rerank": data["rerank"],
                },
            },
            status=status.HTTP_200_OK,
        )


class ChatHistoryView(generics.ListAPIView):
    serializer_class = ChatQuerySerializer

    def get_queryset(self):
        queryset = ChatQuery.objects.all()
        collection = self.request.query_params.get("collection")
        retrieval_mode = self.request.query_params.get("retrieval_mode")

        if collection:
            queryset = queryset.filter(collection__iexact=collection)
        if retrieval_mode:
            valid_modes = {"vector", "hybrid", "metadata-filtered"}
            if retrieval_mode not in valid_modes:
                raise ValidationError(
                    {"retrieval_mode": f"Invalid retrieval mode '{retrieval_mode}'."}
                )
            queryset = queryset.filter(retrieval_mode=retrieval_mode)
        return queryset
