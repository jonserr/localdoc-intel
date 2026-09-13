"""Vector indexing lifecycle: retries, state transitions, and recovery paths."""

from __future__ import annotations

import pytest
import requests
from django.test import override_settings
from django.urls import reverse
from retrieval.services import IndexingResult

from documents import status as status_module
from documents.ingestion import ingest_bytes, reindex_document
from documents.models import Collection, Document, DocumentChunk
from documents.tasks import index_document_chunks_task

MEDIA = "/tmp/localdoc-test-media"


def make_document() -> Document:
    collection = Collection.objects.create(name="Lifecycle")
    document = Document.objects.create(
        collection=collection,
        title="notes.txt",
        original_filename="notes.txt",
        file_type="txt",
        sha256="f" * 64,
        metadata={"vector_indexing": "queued"},
    )
    DocumentChunk.objects.create(document=document, chunk_index=0, text="Synthetic")
    return document


class FlakyProvider:
    """Fails ``failures`` times, then embeds successfully."""

    def __init__(self, failures: int):
        self.failures = failures
        self.calls = 0

    def embed_query(self, text):
        return [0.1, 0.2, 0.3]

    def embed_documents(self, texts):
        self.calls += 1
        if self.calls <= self.failures:
            raise requests.ConnectionError("synthetic Ollama outage")
        return [[0.1, 0.2, 0.3] for _ in texts]


class RecordingStore:
    def __init__(self):
        self.upserts = 0

    def upsert_chunks(self, chunks, vectors):
        self.upserts += 1


def patch_providers(monkeypatch, provider, store):
    monkeypatch.setattr("retrieval.services.OllamaEmbeddingProvider", lambda: provider)
    monkeypatch.setattr("retrieval.services.QdrantVectorStore", lambda: store)


@pytest.mark.django_db
@override_settings(VECTOR_INDEXING_ENABLED=True)
def test_transient_failure_is_retried_and_recovers(monkeypatch):
    document = make_document()
    provider = FlakyProvider(failures=1)
    store = RecordingStore()
    patch_providers(monkeypatch, provider, store)

    result = index_document_chunks_task.apply(args=[document.id], throw=False)

    assert result.state == "SUCCESS"
    assert provider.calls == 2
    assert store.upserts == 1
    document.refresh_from_db()
    assert document.metadata["vector_indexing"] == "succeeded"
    assert document.metadata["vector_indexing_attempts"] == 2
    assert document.metadata["vector_index_error"] == ""
    assert document.metadata["vector_indexed"] == 1
    assert document.metadata["vector_indexed_at"]


@pytest.mark.django_db
@override_settings(VECTOR_INDEXING_ENABLED=True)
def test_retry_exhaustion_marks_task_and_document_failed(monkeypatch):
    document = make_document()
    provider = FlakyProvider(failures=99)
    patch_providers(monkeypatch, provider, RecordingStore())

    result = index_document_chunks_task.apply(args=[document.id], throw=False)

    assert result.state == "FAILURE"
    assert provider.calls == index_document_chunks_task.max_retries + 1
    document.refresh_from_db()
    assert document.metadata["vector_indexing"] == "failed"
    assert document.metadata["vector_indexing_attempts"] == 4
    assert "synthetic Ollama outage" in document.metadata["vector_index_error"]


@pytest.mark.django_db
@override_settings(VECTOR_INDEXING_ENABLED=True)
def test_failed_attempt_with_retry_pending_returns_to_queued(monkeypatch):
    """A retryable failure stays visible: queued again, with the error kept."""
    document = make_document()
    states = []

    def fake_index(document_id):
        document.refresh_from_db()
        states.append(document.metadata["vector_indexing"])
        if len(states) == 1:
            return IndexingResult(indexed=0, skipped=1, enabled=True, error="boom")
        return IndexingResult(indexed=1, skipped=0, enabled=True)

    monkeypatch.setattr("retrieval.services.index_document_chunks", fake_index)

    result = index_document_chunks_task.apply(args=[document.id], throw=False)

    assert result.state == "SUCCESS"
    # Both attempts observed the "running" state when they started.
    assert states == ["running", "running"]
    document.refresh_from_db()
    assert document.metadata["vector_indexing"] == "succeeded"


@pytest.mark.django_db
@override_settings(VECTOR_INDEXING_ENABLED=True)
def test_successful_indexing_clears_queued_state(monkeypatch):
    document = make_document()
    assert document.metadata["vector_indexing"] == "queued"
    monkeypatch.setattr(
        "retrieval.services.index_document_chunks",
        lambda document_id: IndexingResult(indexed=1, skipped=0, enabled=True),
    )

    result = index_document_chunks_task.apply(args=[document.id], throw=False)

    assert result.state == "SUCCESS"
    assert result.result["attempts"] == 1
    document.refresh_from_db()
    assert document.metadata["vector_indexing"] == "succeeded"


@pytest.mark.django_db
def test_task_for_missing_document_does_not_retry():
    result = index_document_chunks_task.apply(args=[999999], throw=False)

    assert result.state == "SUCCESS"
    assert "no longer exists" in result.result["error"]


@pytest.mark.django_db(transaction=True)
@override_settings(
    MEDIA_ROOT=MEDIA, VECTOR_INDEXING_ENABLED=True, ASYNC_INDEXING_ENABLED=True
)
def test_broker_dispatch_failure_falls_back_to_inline_indexing(monkeypatch):
    def failing_delay(document_id):
        raise ConnectionError("broker unavailable")

    monkeypatch.setattr(
        "documents.tasks.index_document_chunks_task.delay", failing_delay
    )
    monkeypatch.setattr(
        "retrieval.services.index_document_chunks",
        lambda document_id: IndexingResult(indexed=1, skipped=0, enabled=True),
    )

    result = ingest_bytes(
        filename="inline.txt", content=b"inline fallback\n", collection_name="Inline"
    )

    result.document.refresh_from_db()
    metadata = result.document.metadata
    assert metadata["vector_indexing"] == "succeeded"
    assert metadata["vector_indexed"] == 1
    assert "broker unavailable" in metadata["vector_indexing_dispatch_error"]


@pytest.mark.django_db(transaction=True)
@override_settings(
    MEDIA_ROOT=MEDIA, VECTOR_INDEXING_ENABLED=True, ASYNC_INDEXING_ENABLED=True
)
def test_reachable_broker_without_worker_leaves_document_queued(monkeypatch):
    """Dispatch succeeds, nobody consumes: the document stays queued, not indexed."""
    monkeypatch.setattr(
        "documents.tasks.index_document_chunks_task.delay", lambda document_id: None
    )

    def never_called(document_id):
        raise AssertionError("inline indexing must not run when dispatch succeeds")

    monkeypatch.setattr("retrieval.services.index_document_chunks", never_called)

    result = ingest_bytes(
        filename="queued.txt", content=b"waiting for a worker\n", collection_name="Q"
    )

    result.document.refresh_from_db()
    assert result.document.status == Document.Status.INDEXED
    assert result.document.metadata["vector_indexing"] == "queued"
    assert "vector_indexed" not in result.document.metadata


@pytest.mark.django_db
@override_settings(MEDIA_ROOT=MEDIA)
def test_disabled_indexing_is_recorded_on_the_document():
    result = ingest_bytes(
        filename="off.txt", content=b"no vectors\n", collection_name="Off"
    )

    assert result.document.metadata["vector_indexing"] == "disabled"


@pytest.mark.django_db(transaction=True)
@override_settings(VECTOR_INDEXING_ENABLED=True, ASYNC_INDEXING_ENABLED=False)
def test_reindex_document_recovers_failed_document(monkeypatch):
    document = make_document()
    document.metadata = {
        "vector_indexing": "failed",
        "vector_index_error": "old error",
        "vector_indexing_attempts": 4,
    }
    document.save()
    monkeypatch.setattr(
        "retrieval.services.index_document_chunks",
        lambda document_id: IndexingResult(indexed=1, skipped=0, enabled=True),
    )

    document = reindex_document(document)

    assert document.metadata["vector_indexing"] == "succeeded"
    assert document.metadata["vector_index_error"] == ""


@pytest.mark.django_db(transaction=True)
@override_settings(VECTOR_INDEXING_ENABLED=True, ASYNC_INDEXING_ENABLED=True)
def test_reindex_endpoint_requeues_document(client, monkeypatch):
    document = make_document()
    document.metadata = {"vector_indexing": "failed", "vector_index_error": "old"}
    document.save()
    queued = []
    monkeypatch.setattr(
        "documents.tasks.index_document_chunks_task.delay", queued.append
    )

    response = client.post(reverse("document-reindex", args=[document.id]))

    assert response.status_code == 202
    assert response.json()["vector_indexing"] == "queued"
    assert queued == [document.id]


@pytest.mark.django_db
def test_stats_report_vector_indexing_states(client):
    document = make_document()
    document.metadata = {"vector_indexing": "failed"}
    document.save()

    payload = client.get(reverse("stats")).json()

    assert payload["documents_by_vector_indexing"]["failed"] == 1
    assert payload["documents_by_vector_indexing"]["queued"] == 0


def test_worker_status_reports_missing_consumer(mocker, settings):
    settings.ASYNC_INDEXING_ENABLED = True
    inspector = mocker.Mock()
    inspector.ping.return_value = None
    mocker.patch("config.celery.app.control.inspect", return_value=inspector)

    result = status_module.celery_worker_status()

    assert result == {"available": False, "enabled": True, "workers": []}


def test_worker_status_lists_pinged_workers(mocker, settings):
    settings.ASYNC_INDEXING_ENABLED = True
    inspector = mocker.Mock()
    inspector.ping.return_value = {"celery@worker-1": {"ok": "pong"}}
    mocker.patch("config.celery.app.control.inspect", return_value=inspector)

    result = status_module.celery_worker_status()

    assert result["available"] is True
    assert result["workers"] == ["celery@worker-1"]
