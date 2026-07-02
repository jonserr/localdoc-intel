"""Celery tasks for asynchronous document processing."""

from __future__ import annotations

from celery import shared_task


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
)
def index_document_chunks_task(self, document_id: int) -> dict:
    """Embed and index a document's chunks in the vector store."""
    from retrieval.services import index_document_chunks

    from .ingestion import apply_indexing_result
    from .models import Document

    result = index_document_chunks(document_id)
    document = Document.objects.filter(id=document_id).first()
    if document is not None:
        apply_indexing_result(document, result)
    return {
        "document_id": document_id,
        "indexed": result.indexed,
        "skipped": result.skipped,
        "error": result.error,
    }
