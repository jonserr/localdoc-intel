from pathlib import Path
from subprocess import CompletedProcess, TimeoutExpired

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse

from documents.ingestion import (
    SUPPORTED_EXTENSIONS,
    IngestionError,
    ingest_bytes,
    ingest_folder,
)
from documents.models import Collection, Document, DocumentChunk


@pytest.mark.django_db
@override_settings(MEDIA_ROOT="/tmp/localdoc-test-media")
def test_upload_txt_ingests_document_and_chunks(client):
    uploaded = SimpleUploadedFile(
        "notes.txt",
        b"alpha beta gamma\nvalidate deployment\nattach logs\n",
        content_type="text/plain",
    )

    response = client.post(
        reverse("document-upload"),
        {
            "collection": "Runbooks",
            "files": [uploaded],
            "chunk_size": "24",
            "overlap": "0",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["received_files"] == 1
    assert payload["errors"] == []

    document = Document.objects.get()
    assert document.collection.name == "Runbooks"
    assert document.file_type == "txt"
    assert document.status == Document.Status.INDEXED
    assert document.sha256
    assert document.source_path.startswith("documents/")
    assert document.metadata["content_type"] == "text"
    assert document.metadata["chunk_count"] == document.chunks.count()

    first_chunk = document.chunks.order_by("chunk_index").first()
    assert first_chunk.start_line == 1
    assert first_chunk.byte_start == 0
    assert first_chunk.token_count > 0


@pytest.mark.django_db
@override_settings(MEDIA_ROOT="/tmp/localdoc-test-media")
def test_upload_is_idempotent_by_collection_and_hash(client):
    content = b"# Deployment\nValidate migrations before release.\n"

    for _ in range(2):
        uploaded = SimpleUploadedFile(
            "deployment.md", content, content_type="text/markdown"
        )
        response = client.post(
            reverse("document-upload"),
            {"collection": "Platform", "files": [uploaded]},
        )
        assert response.status_code == 201

    assert Document.objects.count() == 1
    assert Collection.objects.count() == 1
    document = Document.objects.get()
    assert document.file_type == "md"
    assert document.chunk_count == document.chunks.count()


@pytest.mark.django_db
@override_settings(MEDIA_ROOT="/tmp/localdoc-test-media")
def test_same_file_can_be_ingested_into_different_collections(client):
    content = b"shared content\n"

    for collection in ["A", "B"]:
        uploaded = SimpleUploadedFile("shared.txt", content, content_type="text/plain")
        response = client.post(
            reverse("document-upload"),
            {"collection": collection, "files": [uploaded]},
        )
        assert response.status_code == 201

    assert Document.objects.count() == 2
    assert sorted(Collection.objects.values_list("name", flat=True)) == ["A", "B"]


@pytest.mark.django_db
@override_settings(MEDIA_ROOT="/tmp/localdoc-test-media")
def test_ingestion_strips_nul_bytes_before_saving_chunks():
    result = ingest_bytes(
        filename="nul.txt",
        content=b"boarding\x00 pass\nreceipt total",
        collection_name="Receipts",
    )

    chunk_text = result.document.chunks.get().text
    assert "\x00" not in chunk_text
    assert "boarding pass" in chunk_text


@pytest.mark.django_db
@override_settings(MEDIA_ROOT="/tmp/localdoc-test-media")
def test_upload_code_file_marks_code_metadata(client):
    uploaded = SimpleUploadedFile(
        "router.py",
        b"def route(question):\n    return 'hybrid'\n",
        content_type="text/x-python",
    )

    response = client.post(
        reverse("document-upload"),
        {"collection": "Code", "files": [uploaded]},
    )

    assert response.status_code == 201
    document = Document.objects.get()
    assert document.file_type == "py"
    assert document.metadata["content_type"] == "code"
    assert "route" in document.chunks.get().text


@pytest.mark.django_db
@override_settings(MEDIA_ROOT="/tmp/localdoc-test-media")
def test_text_ingestion_uses_cpp_chunker_when_available(monkeypatch):
    def fake_run(command, **kwargs):
        assert command[0] == "/tmp/localdoc_chunker"
        assert "--input" in command
        return CompletedProcess(
            command,
            0,
            stdout=(
                '{"chunk_index":0,"start_line":1,"end_line":2,'
                '"byte_start":0,"byte_end":30,"text":"from cpp\\nchunked text"}\n'
            ),
            stderr="",
        )

    monkeypatch.setattr(
        "documents.ingestion.find_cpp_chunker",
        lambda: Path("/tmp/localdoc_chunker"),
    )
    monkeypatch.setattr("documents.ingestion.subprocess.run", fake_run)

    result = ingest_bytes(
        filename="notes.md",
        content=b"python fallback should not be used\n",
        collection_name="Chunker",
    )

    document = result.document
    assert document.metadata["chunker"] == "cpp"
    chunk = document.chunks.get()
    assert chunk.text == "from cpp\nchunked text"
    assert chunk.start_line == 1
    assert chunk.byte_end == 30


@pytest.mark.django_db
@override_settings(MEDIA_ROOT="/tmp/localdoc-test-media")
def test_text_ingestion_falls_back_when_cpp_chunker_fails(monkeypatch):
    def fake_run(command, **kwargs):
        raise TimeoutExpired(command, timeout=1)

    monkeypatch.setattr(
        "documents.ingestion.find_cpp_chunker",
        lambda: Path("/tmp/localdoc_chunker"),
    )
    monkeypatch.setattr("documents.ingestion.subprocess.run", fake_run)

    result = ingest_bytes(
        filename="notes.txt",
        content=b"python fallback\nkeeps ingestion available\n",
        collection_name="Fallback",
    )

    document = result.document
    assert document.metadata["chunker"] == "python"
    assert "python fallback" in document.chunks.get().text


@pytest.mark.django_db
@override_settings(MEDIA_ROOT="/tmp/localdoc-test-media")
def test_upload_rejects_unsupported_files(client):
    uploaded = SimpleUploadedFile(
        "archive.zip", b"not supported", content_type="application/zip"
    )

    response = client.post(
        reverse("document-upload"),
        {"collection": "Media", "files": [uploaded]},
    )

    assert response.status_code == 400
    assert Document.objects.count() == 0
    assert response.json()["errors"][0]["filename"] == "archive.zip"


def test_supported_intake_extensions_are_recognized():
    expected = {
        "pdf",
        "png",
        "jpg",
        "jpeg",
        "tif",
        "tiff",
        "txt",
        "md",
        "csv",
        "tsv",
        "json",
        "jsonl",
        "docx",
        "xlsx",
        "html",
        "xml",
        "yaml",
        "rst",
        "log",
        "xlsm",
        "ods",
        "odt",
        "pptx",
        "doc",
        "xls",
        "ppt",
        "eml",
        "msg",
        "rtf",
        "bmp",
        "webp",
    }

    assert expected.issubset(SUPPORTED_EXTENSIONS)


def test_empty_intake_folder_has_clear_error(tmp_path):
    with pytest.raises(IngestionError, match="No intake files found"):
        ingest_folder(tmp_path, collection_name="Empty")


def test_unsupported_intake_files_are_reported(tmp_path):
    (tmp_path / "archive.zip").write_bytes(b"zip")

    with pytest.raises(IngestionError, match=r"Unsupported types: \.zip"):
        ingest_folder(tmp_path, collection_name="Unsupported")


@pytest.mark.django_db
@override_settings(MEDIA_ROOT="/tmp/localdoc-test-media")
def test_ingest_folder_ingests_markdown_and_code(client, tmp_path):
    (tmp_path / "guide.md").write_text(
        "# Guide\nValidate deployment.\n", encoding="utf-8"
    )
    (tmp_path / "script.js").write_text(
        "export const mode = 'hybrid';\n", encoding="utf-8"
    )
    (tmp_path / "ignore.png").write_bytes(b"ignored")

    response = client.post(
        reverse("document-ingest-folder"),
        {"path": str(tmp_path), "collection": "Folder"},
        content_type="application/json",
    )

    assert response.status_code == 201
    assert Document.objects.count() == 2
    assert DocumentChunk.objects.count() == 2
    assert set(Document.objects.values_list("file_type", flat=True)) == {"md", "js"}


@pytest.mark.django_db
@override_settings(MEDIA_ROOT="/tmp/localdoc-test-media")
def test_ingest_folder_reports_unsupported_and_empty_files(tmp_path):
    (tmp_path / "notes.txt").write_text("direct text intake\n", encoding="utf-8")
    (tmp_path / "archive.zip").write_bytes(b"zip")
    (tmp_path / "empty.md").write_bytes(b"")
    (tmp_path / ".hidden.txt").write_text("hidden\n", encoding="utf-8")

    report = ingest_folder(tmp_path, collection_name="Mixed")

    assert report.files_discovered == 3
    assert report.files_ingested == 1
    assert report.files_skipped == 2
    assert report.unsupported_file_types == {".zip": 1}
    assert report.empty_files == 1
    assert report.extraction_failures == 0


@pytest.mark.django_db
@override_settings(MEDIA_ROOT="/tmp/localdoc-test-media")
def test_txt_and_md_files_can_be_ingested_directly(tmp_path):
    (tmp_path / "receipt.txt").write_text("Vendor: TXT Market\n", encoding="utf-8")
    (tmp_path / "notes.md").write_text("# Receipt\nTotal: 12.00\n", encoding="utf-8")

    report = ingest_folder(tmp_path, collection_name="Text")

    assert report.files_ingested == 2
    assert set(Document.objects.values_list("file_type", flat=True)) == {"txt", "md"}


@pytest.mark.django_db
@override_settings(MEDIA_ROOT="/tmp/localdoc-test-media")
def test_csv_and_tsv_files_convert_to_readable_text():
    csv_result = ingest_bytes(
        filename="receipt.csv",
        content=b"item,amount\ncoffee,4.50\nbagel,3.25\n",
        collection_name="Tables",
    )
    tsv_result = ingest_bytes(
        filename="receipt.tsv",
        content=b"item\tamount\ntea\t2.50\n",
        collection_name="Tables",
    )

    assert "Row 1: item: coffee; amount: 4.50" in csv_result.document.chunks.get().text
    assert "Row 1: item: tea; amount: 2.50" in tsv_result.document.chunks.get().text


@pytest.mark.django_db
@override_settings(MEDIA_ROOT="/tmp/localdoc-test-media")
def test_json_and_jsonl_files_convert_to_readable_text():
    json_result = ingest_bytes(
        filename="receipt.json",
        content=b'{"vendor": "JSON Market", "total": 8.75}',
        collection_name="Json",
    )
    jsonl_result = ingest_bytes(
        filename="receipt.jsonl",
        content=b'{"item": "pen", "amount": 1.25}\n{"item": "pad", "amount": 2.50}\n',
        collection_name="Json",
    )

    assert "vendor: JSON Market" in json_result.document.chunks.get().text
    assert "item[1].item: pen" in jsonl_result.document.chunks.get().text


@pytest.mark.django_db
@override_settings(MEDIA_ROOT="/tmp/localdoc-test-media")
def test_ingest_folder_requires_existing_folder(client):
    response = client.post(
        reverse("document-ingest-folder"),
        {"path": "/not/a/folder", "collection": "Missing"},
        content_type="application/json",
    )

    assert response.status_code == 400
    assert "path" in response.json()


@pytest.mark.django_db
@override_settings(MEDIA_ROOT="/tmp/localdoc-test-media")
def test_pdf_ingestion_preserves_page_metadata(monkeypatch):
    class FakePage:
        def __init__(self, text):
            self.text = text

        def extract_text(self):
            return self.text

    class FakeReader:
        def __init__(self, stream):
            self.pages = [
                FakePage("Page one text\nwith source evidence"),
                FakePage("Page two text"),
            ]

    monkeypatch.setattr("documents.ingestion.PdfReader", FakeReader)

    result = ingest_bytes(
        filename="runbook.pdf",
        content=b"%PDF fake bytes",
        collection_name="PDFs",
    )

    document = result.document
    assert document.file_type == "pdf"
    assert document.metadata["content_type"] == "pdf"
    assert document.metadata["page_count"] == 2
    assert document.chunk_count == 2
    assert list(document.chunks.values_list("page", flat=True)) == [1, 2]
    assert document.chunks.first().byte_start is None


@pytest.mark.django_db
@override_settings(MEDIA_ROOT="/tmp/localdoc-test-media")
def test_image_ingestion_uses_local_ocr(monkeypatch):
    monkeypatch.setattr(
        "documents.ingestion.ocr_image_bytes",
        lambda content, extension: "Scanned receipt total is 42 dollars.",
    )

    result = ingest_bytes(
        filename="receipt.png",
        content=b"fake png bytes",
        collection_name="OCR",
    )

    document = result.document
    assert document.file_type == "png"
    assert document.metadata["content_type"] == "image"
    assert document.metadata["parser"] == "tesseract"
    assert document.metadata["ocr"] is True
    assert "receipt total" in document.chunks.get().text


@pytest.mark.django_db
@override_settings(MEDIA_ROOT="/tmp/localdoc-test-media")
def test_pdf_without_text_layer_falls_back_to_ocr(monkeypatch):
    class FakePage:
        def extract_text(self):
            return ""

    class FakeReader:
        def __init__(self, stream):
            self.pages = [FakePage(), FakePage()]

    class FakeOcrPage:
        def __init__(self, page, text):
            self.page = page
            self.text = text

    monkeypatch.setattr("documents.ingestion.PdfReader", FakeReader)
    monkeypatch.setattr(
        "documents.ingestion.ocr_pdf_bytes",
        lambda content: [
            FakeOcrPage(1, "OCR page one mentions incident response."),
            FakeOcrPage(2, "OCR page two mentions recovery steps."),
        ],
    )

    result = ingest_bytes(
        filename="scan.pdf",
        content=b"%PDF fake scan",
        collection_name="OCR",
    )

    document = result.document
    assert document.file_type == "pdf"
    assert document.metadata["content_type"] == "pdf"
    assert document.metadata["parser"] == "pypdf+tesseract"
    assert document.metadata["ocr"] is True
    assert document.chunk_count == 2
    assert list(document.chunks.values_list("page", flat=True)) == [1, 2]
    assert "incident response" in document.chunks.order_by("page").first().text


@pytest.mark.django_db(transaction=True)
@override_settings(
    MEDIA_ROOT="/tmp/localdoc-test-media",
    VECTOR_INDEXING_ENABLED=True,
    ASYNC_INDEXING_ENABLED=True,
)
def test_async_indexing_queues_celery_task(monkeypatch):
    queued = []
    monkeypatch.setattr(
        "documents.tasks.index_document_chunks_task.delay",
        lambda document_id: queued.append(document_id),
    )

    result = ingest_bytes(
        filename="async.txt",
        content=b"queue this for async vector indexing\n",
        collection_name="Async",
    )

    assert result.document.metadata["vector_indexing"] == "queued"
    assert queued == [result.document.id]


@pytest.mark.django_db
@override_settings(
    MEDIA_ROOT="/tmp/localdoc-test-media",
    VECTOR_INDEXING_ENABLED=True,
    ASYNC_INDEXING_ENABLED=False,
)
def test_sync_indexing_records_result(monkeypatch):
    from retrieval.services import IndexingResult

    monkeypatch.setattr(
        "retrieval.services.index_document_chunks",
        lambda document_id: IndexingResult(indexed=1, skipped=0, enabled=True),
    )

    result = ingest_bytes(
        filename="sync.txt",
        content=b"index this inline\n",
        collection_name="Sync",
    )

    assert result.document.metadata["vector_indexed"] == 1
    assert result.document.metadata["vector_index_error"] == ""
