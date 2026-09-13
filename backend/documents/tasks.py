"""Celery tasks for asynchronous document processing."""

from __future__ import annotations

from celery import shared_task


class IndexingFailure(RuntimeError):
    """Raised at the task boundary so Celery's retry mechanism sees failures."""


@shared_task(
    bind=True,
    autoretry_for=(IndexingFailure,),
    retry_backoff=True,
    retry_backoff_max=60,
    max_retries=3,
)
def index_document_chunks_task(self, document_id: int) -> dict:
    """Embed and index a document's chunks in the vector store.

    ``index_document_chunks`` captures provider and store errors as a
    structured ``IndexingResult``. This task records that outcome on the
    document and then raises ``IndexingFailure`` so ``autoretry_for`` retries
    with exponential backoff. The document state goes back to ``queued``
    while a retry is pending and to ``failed`` once retries are exhausted.
    """
    from retrieval.services import index_document_chunks

    from .ingestion import apply_indexing_result, set_vector_indexing_state
    from .models import Document

    document = Document.objects.filter(id=document_id).first()
    if document is None:
        return {
            "document_id": document_id,
            "indexed": 0,
            "skipped": 0,
            "error": "Document no longer exists.",
        }

    attempt = self.request.retries + 1
    set_vector_indexing_state(document, "running", vector_indexing_attempts=attempt)
    result = index_document_chunks(document_id)
    if result.error:
        retry_pending = self.request.retries < self.max_retries
        apply_indexing_result(
            document, result, attempts=attempt, retry_pending=retry_pending
        )
        raise IndexingFailure(result.error)

    apply_indexing_result(document, result, attempts=attempt)
    return {
        "document_id": document_id,
        "indexed": result.indexed,
        "skipped": result.skipped,
        "error": result.error,
        "attempts": attempt,
    }
