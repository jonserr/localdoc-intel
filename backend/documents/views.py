from pathlib import Path

from django.conf import settings
from django.db import connection
from django.db.models import Count, Q
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from .ingestion import IngestionError, ingest_bytes, ingest_folder
from .models import Collection, Document, DocumentChunk
from .serializers import (
    CollectionSerializer,
    DocumentChunkSerializer,
    DocumentSerializer,
)
from .status import system_status


@api_view(["GET"])
def health(request):
    try:
        connection.ensure_connection()
        database = "ok"
        response_status = status.HTTP_200_OK
    except Exception:
        database = "unavailable"
        response_status = status.HTTP_503_SERVICE_UNAVAILABLE

    return Response(
        {
            "status": "ok" if database == "ok" else "degraded",
            "service": "localdoc-intel-backend",
            "database": database,
        },
        status=response_status,
    )


@api_view(["GET"])
def status_view(request):
    """Report availability of local services and whether models are pulled."""
    return Response(system_status())


@api_view(["GET"])
def stats(request):
    latest_document = (
        Document.objects.select_related("collection").order_by("-updated_at").first()
    )
    documents_by_status = {
        row["status"]: row["count"]
        for row in Document.objects.values("status").annotate(count=Count("id"))
    }
    documents_by_file_type = {
        row["file_type"]: row["count"]
        for row in Document.objects.values("file_type").annotate(count=Count("id"))
    }
    return Response(
        {
            "total_documents": Document.objects.count(),
            "total_chunks": DocumentChunk.objects.count(),
            "total_collections": Collection.objects.count(),
            "indexed_collections": Collection.objects.annotate(
                indexed_documents=Count("documents")
            )
            .filter(indexed_documents__gt=0)
            .count(),
            "latest_ingestion_status": (
                latest_document.status if latest_document else "empty"
            ),
            "latest_document": (
                DocumentSerializer(latest_document).data if latest_document else None
            ),
            "documents_by_status": documents_by_status,
            "documents_by_file_type": documents_by_file_type,
        }
    )


@api_view(["GET"])
def local_settings(request):
    return Response(
        {
            "ollama_base_url": settings.OLLAMA_BASE_URL,
            "embedding_model": settings.EMBEDDING_MODEL,
            "llm_model": settings.LLM_MODEL,
            "eval_judge_model": settings.EVAL_JUDGE_MODEL,
            "qdrant_url": settings.QDRANT_URL,
            "redis_url": settings.REDIS_URL,
            "privacy": "Documents are processed locally by the configured services.",
            "features": {
                "document_upload": "available",
                "chat_query": "available",
                "evaluations": "available",
                "ocr": "enabled" if settings.OCR_ENABLED else "disabled",
                "answer_generation": (
                    "enabled" if settings.ANSWER_GENERATION_ENABLED else "disabled"
                ),
                "vector_indexing": (
                    "enabled" if settings.VECTOR_INDEXING_ENABLED else "disabled"
                ),
                "vector_search": (
                    "enabled" if settings.VECTOR_SEARCH_ENABLED else "disabled"
                ),
                "async_indexing": (
                    "enabled" if settings.ASYNC_INDEXING_ENABLED else "disabled"
                ),
            },
            "runtime": {
                **settings.RUNTIME_PROFILE.as_dict(),
                "active": {
                    "ingestion_max_workers": settings.INGESTION_MAX_WORKERS,
                    "celery_worker_concurrency": settings.CELERY_WORKER_CONCURRENCY,
                    "ocr_pdf_dpi": settings.OCR_PDF_DPI,
                    "ocr_timeout_seconds": settings.OCR_TIMEOUT_SECONDS,
                },
            },
            "version": "1.0.0",
        }
    )


class CollectionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Collection.objects.annotate(document_total=Count("documents")).all()
    serializer_class = CollectionSerializer


class DocumentViewSet(viewsets.ModelViewSet):
    queryset = Document.objects.select_related("collection").all()
    serializer_class = DocumentSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        collection = self.request.query_params.get("collection")
        file_type = self.request.query_params.get("file_type")
        status_filter = self.request.query_params.get("status")
        search = self.request.query_params.get("search")

        if collection:
            queryset = queryset.filter(collection__name__iexact=collection)
        if file_type:
            normalized_file_type = file_type.lstrip(".").lower()
            queryset = queryset.filter(file_type__iexact=normalized_file_type)
        if status_filter:
            valid_statuses = {choice.value for choice in Document.Status}
            if status_filter not in valid_statuses:
                raise ValidationError({"status": f"Invalid status '{status_filter}'."})
            queryset = queryset.filter(status=status_filter)
        if search:
            queryset = queryset.filter(
                Q(title__icontains=search) | Q(original_filename__icontains=search)
            )
        return queryset

    @action(detail=True, methods=["get"])
    def chunks(self, request, pk=None):
        document = self.get_object()
        serializer = DocumentChunkSerializer(
            document.chunks.select_related("document", "document__collection"),
            many=True,
        )
        return Response(serializer.data)


class DocumentChunkViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = DocumentChunkSerializer
    queryset = DocumentChunk.objects.select_related("document", "document__collection")

    def get_queryset(self):
        queryset = super().get_queryset()
        document_id = self.request.query_params.get("document_id")
        collection = self.request.query_params.get("collection")
        search = self.request.query_params.get("search")

        if document_id:
            try:
                document_pk = int(document_id)
            except ValueError as exc:
                raise ValidationError({"document_id": "Must be an integer."}) from exc
            queryset = queryset.filter(document_id=document_pk)
        if collection:
            queryset = queryset.filter(document__collection__name__iexact=collection)
        if search:
            queryset = queryset.filter(text__icontains=search)
        return queryset


class UploadDocumentView(APIView):
    def post(self, request):
        uploaded_files = request.FILES.getlist("files") or request.FILES.getlist("file")
        if not uploaded_files:
            raise ValidationError({"files": "Upload at least one file."})

        collection_name = request.data.get("collection") or "Default"
        chunk_size = _positive_int(request.data.get("chunk_size"), default=1200)
        overlap = _non_negative_int(request.data.get("overlap"), default=150)

        documents = []
        errors = []
        for uploaded_file in uploaded_files:
            try:
                result = ingest_bytes(
                    filename=uploaded_file.name,
                    content=uploaded_file.read(),
                    collection_name=collection_name,
                    chunk_size=chunk_size,
                    overlap=overlap,
                )
                documents.append(
                    {
                        "document": DocumentSerializer(result.document).data,
                        "created": result.created,
                        "chunks_created": result.chunks_created,
                        "chunks_updated": result.chunks_updated,
                    }
                )
            except Exception as exc:
                errors.append({"filename": uploaded_file.name, "error": str(exc)})

        response_status = (
            status.HTTP_201_CREATED if documents else status.HTTP_400_BAD_REQUEST
        )
        return Response(
            {
                "detail": f"Ingested {len(documents)} of {len(uploaded_files)} uploaded files.",
                "received_files": len(uploaded_files),
                "documents": documents,
                "errors": errors,
            },
            status=response_status,
        )


class IngestFolderView(APIView):
    def post(self, request):
        folder_path = request.data.get("path") or request.data.get("folder")
        if not folder_path:
            raise ValidationError({"path": "Folder path is required."})

        collection_name = request.data.get("collection") or "Default"
        chunk_size = _positive_int(request.data.get("chunk_size"), default=1200)
        overlap = _non_negative_int(request.data.get("overlap"), default=150)

        try:
            report = ingest_folder(
                folder=Path(folder_path),
                collection_name=collection_name,
                chunk_size=chunk_size,
                overlap=overlap,
            )
        except IngestionError as exc:
            raise ValidationError({"path": str(exc)}) from exc

        return Response(
            {
                "detail": f"Ingested {report.files_ingested} files from folder.",
                "summary": {
                    "files_discovered": report.files_discovered,
                    "files_ingested": report.files_ingested,
                    "files_skipped": report.files_skipped,
                    "unsupported_file_types": report.unsupported_file_types,
                    "empty_files": report.empty_files,
                    "extraction_failures": report.extraction_failures,
                },
                "documents": [
                    {
                        "document": DocumentSerializer(result.document).data,
                        "created": result.created,
                        "chunks_created": result.chunks_created,
                        "chunks_updated": result.chunks_updated,
                    }
                    for result in report.results
                ],
                "errors": report.errors,
            },
            status=status.HTTP_201_CREATED,
        )


def _positive_int(value, default: int) -> int:
    if value in (None, ""):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError({"chunk_size": "Must be an integer."}) from exc
    if parsed <= 0:
        raise ValidationError({"chunk_size": "Must be greater than zero."})
    return parsed


def _non_negative_int(value, default: int) -> int:
    if value in (None, ""):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError({"overlap": "Must be an integer."}) from exc
    if parsed < 0:
        raise ValidationError({"overlap": "Must be zero or greater."})
    return parsed
