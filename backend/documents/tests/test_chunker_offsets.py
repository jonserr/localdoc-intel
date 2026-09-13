"""Python chunker line semantics and byte-offset provenance (no C++ binary)."""

from __future__ import annotations

import pytest
from django.test import override_settings

from documents.ingestion import LINE_BREAK, _chunk_text, _line_records, ingest_bytes

MEDIA = "/tmp/localdoc-test-media"

# Inputs shared with the real-binary parity tests in test_cpp_integration.py.
SEPARATOR_CASES = {
    "lf": b"alpha\nbeta\ngamma",
    "crlf": b"alpha\r\nbeta\r\ngamma",
    "lone_cr": b"alpha\rbeta\rgamma",
    "mixed": b"alpha\r\nbeta\rgamma\ndelta\r\n\nepsilon",
    "trailing_newline": b"alpha\nbeta\n",
    "trailing_crlf": b"alpha\r\nbeta\r\n",
    "blank_lines": b"\n\nalpha\n\n\nbeta\n\n",
    "multibyte": "naïve café — piñata ≈ 42µs\n日本語のテキスト\r\nемодзи 🚀 end".encode(),
    "unicode_separators": (
        "one still one still one\x0cstill one\x0bstill one\x85still one\n" "two"
    ).encode(),
    "long_line": b"x" * 5000 + b"\nshort\n" + b"y" * 3000,
    "only_newlines": b"\n\n\n",
    "empty": b"",
}


def round_trip(chunks, content: bytes) -> list[str]:
    """Decode each chunk's byte range and normalize separators to LF."""
    return [
        content[chunk.byte_start : chunk.byte_end]
        .decode("utf-8")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        for chunk in chunks
    ]


@pytest.mark.parametrize("name", sorted(SEPARATOR_CASES))
@pytest.mark.parametrize("chunk_size,overlap", [(6, 0), (12, 4), (1200, 150)])
def test_python_offsets_address_original_bytes(name, chunk_size, overlap):
    content = SEPARATOR_CASES[name]
    chunks = _chunk_text(
        content.decode("utf-8"),
        page=None,
        start_index=0,
        chunk_size=chunk_size,
        overlap=overlap,
        include_byte_offsets=True,
    )

    assert round_trip(chunks, content) == [chunk.text for chunk in chunks]
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
    for chunk in chunks:
        assert 0 <= chunk.byte_start <= chunk.byte_end <= len(content)


def test_crlf_line_records_use_two_byte_separators():
    records = _line_records("alpha\r\nbeta\r\ngamma")

    assert [(r["text"], r["byte_start"], r["byte_end"]) for r in records] == [
        ("alpha", 0, 5),
        ("beta", 7, 11),
        ("gamma", 13, 18),
    ]


def test_lone_cr_and_mixed_separators_count_as_line_breaks():
    records = _line_records("a\rb\r\nc\nd")

    assert [r["text"] for r in records] == ["a", "b", "c", "d"]
    assert [r["line_number"] for r in records] == [1, 2, 3, 4]
    assert [r["byte_start"] for r in records] == [0, 2, 5, 7]


def test_unicode_separators_stay_inside_the_line():
    text = "one two\x0cthree\x85four\nfive"
    records = _line_records(text)

    # str.splitlines() would produce five lines; the shared rule produces two.
    assert len(text.splitlines()) == 5
    assert [r["text"] for r in records] == ["one two\x0cthree\x85four", "five"]
    assert LINE_BREAK.pattern == r"\r\n|\r|\n"


def test_trailing_newline_does_not_create_an_empty_line():
    assert [r["text"] for r in _line_records("alpha\nbeta\n")] == ["alpha", "beta"]
    assert [r["text"] for r in _line_records("alpha\r\n")] == ["alpha"]
    assert _line_records("") == []


def test_multibyte_characters_use_utf8_byte_lengths():
    records = _line_records("日本語\né")

    assert records[0]["byte_end"] == 9
    assert records[1]["byte_start"] == 10
    assert records[1]["byte_end"] == 12


def test_long_line_becomes_a_single_oversized_chunk():
    text = "x" * 5000 + "\nshort"
    chunks = _chunk_text(text, None, 0, 1200, 150, include_byte_offsets=True)

    assert chunks[0].text == "x" * 5000
    assert chunks[0].byte_end == 5000
    assert chunks[-1].text == "short"


@pytest.mark.django_db
@override_settings(MEDIA_ROOT=MEDIA)
def test_clean_text_file_reports_source_byte_offsets():
    result = ingest_bytes(
        filename="clean.txt",
        content=b"alpha\r\nbeta\r\ngamma\r\n",
        collection_name="Provenance",
    )

    document = result.document
    assert document.metadata["offset_basis"] == "source_bytes"
    assert document.metadata["decode_errors"] is False
    assert document.metadata["null_bytes_removed"] is False
    chunk = document.chunks.get()
    assert chunk.text == "alpha\nbeta\ngamma"
    assert (chunk.byte_start, chunk.byte_end) == (0, 18)  # excludes the final CRLF


@pytest.mark.django_db
@override_settings(MEDIA_ROOT=MEDIA)
def test_decoding_errors_disable_source_byte_provenance(monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("files with decode errors must stay on Python")

    monkeypatch.setattr("documents.ingestion.CPP_CHUNKER_THRESHOLD_BYTES", 0)
    monkeypatch.setattr("documents.ingestion.run_cpp_chunker", fail_if_called)

    result = ingest_bytes(
        filename="latin1.txt",
        content=b"caf\xe9 au lait\nsecond line\n",
        collection_name="Provenance",
    )

    document = result.document
    assert document.metadata["decode_errors"] is True
    assert document.metadata["offset_basis"] == "extracted_text"
    assert document.metadata["chunker"] == "python"
    assert "caf� au lait" in document.chunks.get().text


@pytest.mark.django_db
@override_settings(MEDIA_ROOT=MEDIA)
def test_sanitized_null_bytes_disable_source_byte_provenance(monkeypatch):
    monkeypatch.setattr("documents.ingestion.CPP_CHUNKER_THRESHOLD_BYTES", 0)
    monkeypatch.setattr(
        "documents.ingestion.run_cpp_chunker",
        lambda *args, **kwargs: pytest.fail("NUL-containing files stay on Python"),
    )

    result = ingest_bytes(
        filename="nulls.log",
        content=b"alpha\x00beta\ngamma\n",
        collection_name="Provenance",
    )

    document = result.document
    assert document.metadata["null_bytes_removed"] is True
    assert document.metadata["offset_basis"] == "extracted_text"
    assert document.chunks.get().text == "alphabeta\ngamma"


@pytest.mark.django_db
@override_settings(MEDIA_ROOT=MEDIA)
def test_transformed_formats_report_extracted_text_offsets():
    result = ingest_bytes(
        filename="table.csv",
        content=b"name,total\nAmtrak,53.00\n",
        collection_name="Provenance",
    )

    assert result.document.metadata["offset_basis"] == "extracted_text"


@pytest.mark.django_db
@override_settings(MEDIA_ROOT=MEDIA)
def test_paged_documents_report_no_byte_offsets(monkeypatch):
    from documents.ingestion import ParsedSource

    monkeypatch.setattr(
        "documents.ingestion.parse_document",
        lambda filename, content, source_path="": [
            ParsedSource(
                title=filename,
                text="page text",
                page=1,
                metadata={"filename": filename, "extension": "pdf", "parser": "x"},
            )
        ],
    )

    result = ingest_bytes(
        filename="scan.pdf", content=b"%PDF-1.4", collection_name="Provenance"
    )

    assert result.document.metadata["offset_basis"] == "none"
    assert result.document.chunks.get().byte_start is None
