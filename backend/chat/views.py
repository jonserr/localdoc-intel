import time

import requests
from django.conf import settings
from django.shortcuts import get_object_or_404
from documents.models import Document, DocumentChunk
from rest_framework import generics, status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView
from retrieval.services import retrieve

from .analysis import (
    AnalysisError,
    analysis_references,
    analysis_summary,
    cancel_analysis,
    completed_analysis,
    expire_stalled_analysis,
    inventory_target,
    name_key,
    reference_value,
    start_analysis,
)
from .generation import generate_answer
from .models import ChatQuery, CollectionAnalysis
from .serializers import ChatQueryRequestSerializer, ChatQuerySerializer


class ChatQueryView(APIView):
    def post(self, request):
        serializer = ChatQueryRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        started = time.perf_counter()
        if data.get("review_id") and (value := reference_value(data["question"])):
            job = get_object_or_404(CollectionAnalysis, pk=data["review_id"])
            if (
                job.collection.casefold() == data.get("collection", "").casefold()
                and name_key(value) in job.entries
            ):
                response = analysis_references(job, value)
                response["question"] = data["question"]
                query = ChatQuery.objects.create(
                    question=data["question"],
                    answer=response["answer"],
                    collection=job.collection,
                    retrieval_mode=data["retrieval_mode"],
                    retrieval_top_k=data["top_k"],
                    citation_count=len(response["citations"]),
                    latency_ms=int((time.perf_counter() - started) * 1000),
                )
                response["id"] = query.id
                response["metadata"]["latency_ms"] = query.latency_ms
                return Response(response)
        if data["analysis_scope"] != "retrieved":
            saved = completed_analysis(data)
            if saved:
                return Response(analysis_summary(saved, cached=True))
        target = None
        routing_error = ""
        try:
            if data["analysis_scope"] != "retrieved":
                target = inventory_target(data["question"], data["analysis_scope"])
        except (AnalysisError, requests.RequestException, ValueError) as exc:
            if data["analysis_scope"] == "collection":
                return Response(
                    {"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE
                )
            # Preserve ordinary chat's extractive fallback when local planning
            # is unavailable; the response explicitly reports the smaller scope.
            routing_error = str(exc)
        if target:
            job, cached = start_analysis(data, target)
            return Response(
                analysis_summary(job, cached),
                status=(
                    status.HTTP_202_ACCEPTED
                    if job.status in {"queued", "running"}
                    else status.HTTP_200_OK
                ),
            )
        outcome = retrieve(
            question=data["question"],
            collection=data.get("collection") or None,
            top_k=data["top_k"],
            mode=data["retrieval_mode"],
            rerank=data["rerank"],
        )
        retrieved = outcome.chunks
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

        # Scope sizes describe stored content, not entity counts or vector-index
        # coverage. Match retrieval's optional, case-insensitive collection filter.
        documents = Document.objects.all()
        chunks = DocumentChunk.objects.all()
        if data.get("collection"):
            documents = documents.filter(collection__name__iexact=data["collection"])
            chunks = chunks.filter(
                document__collection__name__iexact=data["collection"]
            )
        collection_document_count = documents.count()
        collection_chunk_count = chunks.count()

        generation = generate_answer(
            data["question"],
            retrieved,
            collection_document_count=collection_document_count,
            collection_chunk_count=collection_chunk_count,
            use_cache=True,
        )
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
                    # What actually ran; differs from retrieval_mode on fallback.
                    "retrieval_strategy": outcome.strategy,
                    "retrieval_fallback_reason": outcome.fallback_reason,
                    "retrieval_top_k": data["top_k"],
                    "retrieved_source_count": len(retrieved),
                    "collection_document_count": collection_document_count,
                    "collection_chunk_count": collection_chunk_count,
                    "embedding_model": settings.EMBEDDING_MODEL,
                    "llm_model": settings.LLM_MODEL,
                    "answer_mode": generation.mode,
                    "answer_cached": generation.cached,
                    "analysis_routing_error": routing_error,
                    "generation_error": generation.error,
                    # Marker validation only: numbers refer to supplied sources.
                    # It does not verify that each claim is supported.
                    "citation_status": generation.citation_status,
                    "cited_sources": generation.cited_sources,
                    "invalid_citations": generation.invalid_citations,
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


class CollectionAnalysisView(APIView):
    def get(self, request, analysis_id):
        job = get_object_or_404(CollectionAnalysis, pk=analysis_id)
        expire_stalled_analysis(job)
        return Response(analysis_summary(job))


class CollectionAnalysisControlView(APIView):
    def post(self, request, analysis_id):
        job = get_object_or_404(CollectionAnalysis, pk=analysis_id)
        action = request.data.get("action")
        if action == "cancel":
            return Response(analysis_summary(cancel_analysis(job)))
        if action == "resume":
            job, cached = start_analysis(job.request_metadata, job.target)
            return Response(analysis_summary(job, cached))
        return Response({"detail": "action must be cancel or resume"}, status=400)


class ActiveCollectionAnalysesView(APIView):
    def get(self, request):
        jobs = CollectionAnalysis.objects.filter(
            status__in=["queued", "running"]
        ).order_by("created_at")
        responses = []
        for job in jobs:
            expire_stalled_analysis(job)
            responses.append(analysis_summary(job))
        return Response(responses)


class CollectionAnalysisReferencesView(APIView):
    def get(self, request, analysis_id):
        value = request.query_params.get("value", "").strip()
        if not value:
            raise ValidationError({"value": "An extracted name or value is required."})
        job = get_object_or_404(CollectionAnalysis, pk=analysis_id)
        return Response(analysis_references(job, value))
