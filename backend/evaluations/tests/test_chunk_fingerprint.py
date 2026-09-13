"""Re-chunking identical bytes must change the saved retrieval identity."""

import pytest
from django.test import override_settings
from documents.ingestion import ingest_bytes
from documents.models import DocumentChunk

from evaluations.harness import chunk_fingerprint, corpus_fingerprint

COLLECTION = "Fingerprint"
SOURCE = (
    b"Validate database migrations before promotion.\n"
    b"Check cache connectivity and health endpoints.\n"
    b"Halt promotion on failure and attach the logs.\n"
)


def ingest(chunk_size: int) -> None:
    ingest_bytes(
        filename="runbook.txt",
        content=SOURCE,
        collection_name=COLLECTION,
        chunk_size=chunk_size,
        overlap=0,
    )


@pytest.mark.django_db
@override_settings(MEDIA_ROOT="/tmp/localdoc-test-media")
def test_rechunking_changes_the_chunk_hash_but_not_the_corpus_hash():
    ingest(chunk_size=4000)
    whole_document = chunk_fingerprint(COLLECTION)
    source_identity = corpus_fingerprint(COLLECTION)
    assert whole_document[1] == 1

    ingest(chunk_size=48)
    rechunked = chunk_fingerprint(COLLECTION)

    # Same bytes, so source identity is unchanged by design.
    assert corpus_fingerprint(COLLECTION) == source_identity
    assert rechunked[1] > whole_document[1]
    assert rechunked[0] != whole_document[0]


@pytest.mark.django_db
@override_settings(MEDIA_ROOT="/tmp/localdoc-test-media")
def test_identical_ingestion_reproduces_the_chunk_hash():
    ingest(chunk_size=48)
    first = chunk_fingerprint(COLLECTION)

    ingest(chunk_size=48)

    assert chunk_fingerprint(COLLECTION) == first


@pytest.mark.django_db
@override_settings(MEDIA_ROOT="/tmp/localdoc-test-media")
def test_edited_chunk_text_changes_the_chunk_hash():
    ingest(chunk_size=48)
    before = chunk_fingerprint(COLLECTION)
    chunk = DocumentChunk.objects.order_by("chunk_index").first()

    chunk.text = f"{chunk.text} appended"
    chunk.save(update_fields=["text"])

    assert chunk_fingerprint(COLLECTION)[0] != before[0]


@pytest.mark.django_db
@override_settings(MEDIA_ROOT="/tmp/localdoc-test-media")
def test_ocr_settings_are_part_of_the_chunk_hash():
    ingest(chunk_size=48)
    with override_settings(OCR_PDF_DPI=200):
        at_200_dpi = chunk_fingerprint(COLLECTION)
    with override_settings(OCR_PDF_DPI=300):
        at_300_dpi = chunk_fingerprint(COLLECTION)

    assert at_200_dpi[0] != at_300_dpi[0]


@pytest.mark.django_db
def test_empty_corpus_fingerprints_without_error():
    assert chunk_fingerprint(COLLECTION)[1] == 0
