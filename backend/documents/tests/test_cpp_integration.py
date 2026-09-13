"""Real C++ chunker integration.

These tests run only when a built ``localdoc_chunker`` binary is discoverable
(``make cpp-build`` on the host, or the backend Docker image). They compare
every chunk field against the Python chunker and verify that ingestion of an
eligible file (> 4 MiB) really uses the binary.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from django.test import override_settings

from documents.ingestion import (
    CPP_CHUNKER_THRESHOLD_BYTES,
    _chunk_text,
    find_cpp_chunker,
    ingest_bytes,
    run_cpp_chunker,
)
from documents.tests.test_chunker_offsets import SEPARATOR_CASES, round_trip

MEDIA = "/tmp/localdoc-test-media"
FIELDS = (
    "chunk_index",
    "text",
    "start_line",
    "end_line",
    "byte_start",
    "byte_end",
    "token_count",
)

BINARY = find_cpp_chunker()
# make test and make packaged-test set LOCALDOC_REQUIRE_CPP=1, so a missing
# binary fails instead of quietly skipping the only real-integration tests.
REQUIRE_CPP = os.environ.get("LOCALDOC_REQUIRE_CPP") == "1"
if BINARY is None and REQUIRE_CPP:
    raise RuntimeError(
        "LOCALDOC_REQUIRE_CPP=1 but no localdoc_chunker binary was found. "
        "Run make cpp-build, or unset LOCALDOC_REQUIRE_CPP."
    )
pytestmark = pytest.mark.skipif(
    BINARY is None, reason="no localdoc_chunker binary; run make cpp-build"
)


def python_chunks(content: bytes, chunk_size: int, overlap: int):
    return _chunk_text(
        content.decode("utf-8"),
        page=None,
        start_index=0,
        chunk_size=chunk_size,
        overlap=overlap,
        include_byte_offsets=True,
    )


@pytest.mark.parametrize("name", sorted(SEPARATOR_CASES))
@pytest.mark.parametrize("chunk_size,overlap", [(6, 0), (12, 4), (1200, 150)])
def test_real_binary_matches_python_on_every_field(tmp_path, name, chunk_size, overlap):
    content = SEPARATOR_CASES[name]
    path = tmp_path / f"{name}.txt"
    path.write_bytes(content)

    expected = python_chunks(content, chunk_size, overlap)
    actual = run_cpp_chunker(path, 0, chunk_size, overlap, source_bytes=content)

    assert actual is not None, "binary produced no chunks"
    assert [[getattr(c, f) for f in FIELDS] for c in actual] == [
        [getattr(c, f) for f in FIELDS] for c in expected
    ]
    assert round_trip(actual, content) == [chunk.text for chunk in actual]


def test_real_binary_rejects_missing_input(tmp_path):
    completed = subprocess.run(
        [str(BINARY), "--input", str(tmp_path / "missing.txt")],
        capture_output=True,
    )

    assert completed.returncode == 1
    assert b"Could not open" in completed.stderr


@pytest.mark.django_db
@override_settings(MEDIA_ROOT=MEDIA)
def test_ingestion_of_eligible_file_uses_real_binary():
    line = b"2026-01-01T00:00:00 INFO worker-1 ingest chunk embed retrieve\r\n"
    repeats = CPP_CHUNKER_THRESHOLD_BYTES // len(line) + 2
    content = line * repeats
    assert len(content) > CPP_CHUNKER_THRESHOLD_BYTES

    result = ingest_bytes(
        filename="large.log",
        content=content,
        collection_name="Integration",
        chunk_size=20000,
        overlap=0,
    )

    document = result.document
    assert document.metadata["chunker"] == "cpp"
    assert document.metadata["offset_basis"] == "source_bytes"
    chunks = list(document.chunks.order_by("chunk_index"))
    assert len(chunks) == document.chunk_count > 200
    assert round_trip(chunks, content) == [chunk.text for chunk in chunks]
    assert chunks[0].start_line == 1
    assert chunks[-1].end_line == repeats
    assert chunks[-1].byte_end == len(content) - len(b"\r\n")


@pytest.mark.django_db
@override_settings(MEDIA_ROOT=MEDIA)
def test_ingestion_falls_back_to_python_when_binary_is_missing(monkeypatch):
    monkeypatch.setenv("LOCALDOC_CHUNKER_PATH", "/nonexistent/localdoc_chunker")
    monkeypatch.setattr("documents.ingestion.find_cpp_chunker", lambda: None)

    result = ingest_bytes(
        filename="small.log", content=b"one\ntwo\n", collection_name="Integration"
    )

    assert result.document.metadata["chunker"] == "python"


def test_binary_is_installed_outside_bind_mounts_in_docker():
    """Inside the image the binary lives at /usr/local/bin, not under /cpp."""
    if not Path("/.dockerenv").exists():
        pytest.skip("only meaningful inside the backend container")
    assert Path("/usr/local/bin/localdoc_chunker") == BINARY
