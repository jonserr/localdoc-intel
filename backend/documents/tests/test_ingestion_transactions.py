"""Real commits verify that expensive work runs outside write transactions."""

from unittest.mock import Mock

import pytest
from django.db import connection, transaction
from retrieval.services import IndexingResult

from documents import ingestion
from documents.models import Collection, Document, DocumentChunk

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path


def ingest():
    return ingestion.ingest_bytes(
        filename="transaction.txt",
        content=b"first line\nsecond line\n",
        collection_name="Transactions",
        chunk_size=12,
        overlap=0,
    )


@pytest.mark.parametrize(
    "async_enabled,broker_fails", [(False, False), (True, False), (True, True)]
)
def test_slow_work_and_dispatch_run_after_or_before_transaction(
    settings, monkeypatch, async_enabled, broker_fails
):
    settings.VECTOR_INDEXING_ENABLED = True
    settings.ASYNC_INDEXING_ENABLED = async_enabled
    events = []
    for name in ["parse_document", "chunk_parsed_sources"]:
        original = getattr(ingestion, name)

        def wrapped(*args, _name=name, _original=original, **kwargs):
            assert not connection.in_atomic_block
            assert connection.get_autocommit()
            events.append(_name)
            return _original(*args, **kwargs)

        monkeypatch.setattr(ingestion, name, wrapped)

    def check_committed(document_id):
        assert not connection.in_atomic_block
        assert connection.get_autocommit()
        assert Document.objects.get(id=document_id).chunks.count() == 2

    def index(document_id):
        check_committed(document_id)
        events.append("index")
        return IndexingResult(indexed=2, skipped=0, enabled=True)

    def dispatch(document_id):
        check_committed(document_id)
        events.append("dispatch")
        if broker_fails:
            raise ConnectionError("synthetic broker outage")

    monkeypatch.setattr("retrieval.services.index_document_chunks", index)
    monkeypatch.setattr("documents.tasks.index_document_chunks_task.delay", dispatch)
    result = ingest()
    assert events == ["parse_document", "chunk_parsed_sources"] + (
        ["index"]
        if not async_enabled
        else ["dispatch", "index"] if broker_fails else ["dispatch"]
    )
    result.document.refresh_from_db()
    assert result.document.metadata["vector_indexing"] == (
        "queued" if async_enabled and not broker_fails else "succeeded"
    )


def test_chunk_write_failure_rolls_back_reingestion_and_never_indexes(
    settings, monkeypatch
):
    original = ingest().document
    old_chunks = list(original.chunks.values_list("id", "text"))
    old_metadata = original.metadata
    settings.VECTOR_INDEXING_ENABLED = True
    index = Mock()
    monkeypatch.setattr("retrieval.services.index_document_chunks", index)
    real_update = DocumentChunk.objects.update_or_create
    calls = 0

    def fail_second(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("synthetic database write failure")
        kwargs["defaults"]["text"] = "must be rolled back"
        return real_update(*args, **kwargs)

    monkeypatch.setattr(DocumentChunk.objects, "update_or_create", fail_second)
    with pytest.raises(RuntimeError, match="database write"):
        ingest()
    original.refresh_from_db()
    assert original.metadata == old_metadata
    assert list(original.chunks.values_list("id", "text")) == old_chunks
    index.assert_not_called()


@pytest.mark.parametrize("async_enabled", [False, True])
def test_enclosing_rollback_never_publishes_vectors(
    settings, monkeypatch, async_enabled
):
    settings.VECTOR_INDEXING_ENABLED = True
    settings.ASYNC_INDEXING_ENABLED = async_enabled
    index = Mock()
    dispatch = Mock()
    monkeypatch.setattr("retrieval.services.index_document_chunks", index)
    monkeypatch.setattr("documents.tasks.index_document_chunks_task.delay", dispatch)
    with pytest.raises(RuntimeError, match="rollback"), transaction.atomic():
        ingest()
        index.assert_not_called()
        dispatch.assert_not_called()
        raise RuntimeError("rollback")
    assert not Document.objects.exists()
    assert not DocumentChunk.objects.exists()
    assert not Collection.objects.exists()
    index.assert_not_called()
    dispatch.assert_not_called()


def test_parser_failure_creates_no_database_rows(monkeypatch):
    def fail(*args, **kwargs):
        assert not connection.in_atomic_block
        raise ingestion.IngestionError("synthetic parser failure")

    monkeypatch.setattr(ingestion, "parse_document", fail)
    with pytest.raises(ingestion.IngestionError):
        ingest()
    assert not Collection.objects.exists()
    assert not Document.objects.exists()


def test_sync_provider_failure_keeps_text_and_records_failed_state(
    settings, monkeypatch
):
    settings.VECTOR_INDEXING_ENABLED = True

    def fail(document_id):
        assert not connection.in_atomic_block
        return IndexingResult(
            indexed=0, skipped=2, enabled=True, error="synthetic model outage"
        )

    monkeypatch.setattr("retrieval.services.index_document_chunks", fail)
    result = ingest()
    result.document.refresh_from_db()
    assert result.document.chunks.count() == 2
    assert result.document.metadata["vector_indexing"] == "failed"
    assert result.document.metadata["vector_index_error"] == "synthetic model outage"
