#!/usr/bin/env python
"""Benchmark the Python chunker against the optional C++ chunker.

Measures latency on deterministic corpora and verifies that both chunkers
produce the same chunks. Also checks that byte offsets address the raw file.

This measures the chunker pipeline only: reading bytes, splitting, and
building chunk payloads. It is not an end-to-end ingestion benchmark, which
also includes parsing, OCR, database writes, embedding, and indexing.

Usage:
    python scripts/benchmark_chunker.py [--sizes 0.0625,0.5,4,32] [--runs 5]
    python scripts/benchmark_chunker.py --json results.json
"""

from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

CHUNK_SIZE = 1200
OVERLAP = 150
FIELDS = (
    "chunk_index",
    "text",
    "start_line",
    "end_line",
    "byte_start",
    "byte_end",
    "token_count",
)
WORDS = [
    "ingest",
    "chunk",
    "embed",
    "retrieve",
    "rerank",
    "collection",
    "qdrant",
    "celery",
    "worker",
    "latency",
    "payload",
    "document",
    "receipt",
    "vendor",
    "invoice",
    "timeout",
    "retry",
    "batch",
    "offset",
    "token",
    "vector",
    "hybrid",
    "keyword",
    "dense",
    "score",
    "threshold",
    "cache",
    "flush",
]


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def bootstrap_django() -> None:
    root = repo_root()
    for candidate in (root / "backend", Path("/app")):
        if candidate.exists():
            sys.path.insert(0, str(candidate))
            break
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django

    django.setup()


def build_corpus(
    path: Path, target_bytes: int, newline: str, unicode_ratio: float
) -> Path:
    # Deterministic log-like corpus, seeded for reproducible runs
    rng = random.Random(1234)
    written = 0
    with open(path, "w", encoding="utf-8", newline="") as handle:
        while written < target_bytes:
            body = " ".join(rng.choice(WORDS) for _ in range(rng.randint(4, 18)))
            if unicode_ratio and rng.random() < unicode_ratio:
                body = f"{body} naïve café — piñata ≈ 42µs"
            line = (
                f"2026-01-01T{rng.randint(0, 23):02d}:{rng.randint(0, 59):02d}:"
                f"{rng.randint(0, 59):02d} INFO worker-{rng.randint(1, 8)} {body}"
            )
            handle.write(line + newline)
            written += len(line.encode("utf-8")) + len(newline)
    return path


def measure(function, path: Path, runs: int) -> tuple[dict, object]:
    samples = []
    payload = None
    for _ in range(runs):
        elapsed, chunks = function(path)
        samples.append(elapsed * 1000)
        if chunks is not None:
            payload = chunks
    return (
        {
            "median_ms": statistics.median(samples),
            "min_ms": min(samples),
            "max_ms": max(samples),
            "runs": runs,
        },
        payload,
    )


def compare_chunks(python_chunks, cpp_chunks) -> dict:
    # Field-level equality between the two chunkers
    report = {
        "python_chunks": len(python_chunks),
        "cpp_chunks": len(cpp_chunks or []),
        "identical": False,
        "field_mismatches": {},
    }
    if not cpp_chunks:
        report["error"] = "cpp chunker returned nothing"
        return report
    for left, right in zip(python_chunks, cpp_chunks, strict=False):
        for field in FIELDS:
            if getattr(left, field) != getattr(right, field):
                counts = report["field_mismatches"]
                counts[field] = counts.get(field, 0) + 1
    report["identical"] = not report["field_mismatches"] and len(python_chunks) == len(
        cpp_chunks
    )
    return report


def offsets_round_trip(chunks, path: Path, newline: str) -> str:
    # Byte offsets must address the raw file, including multi-byte separators
    if not chunks:
        return "n/a"
    data = path.read_bytes()
    correct = 0
    for chunk in chunks:
        if chunk.byte_start is None or chunk.byte_end is None:
            continue
        expected = chunk.text.replace("\n", newline).encode("utf-8")
        if data[chunk.byte_start : chunk.byte_end] == expected:
            correct += 1
    return f"{correct}/{len(chunks)}"


CASES = [
    ("crlf_512KB", 0.5, "\r\n", 0.0),
    ("unicode_512KB", 0.5, "\n", 0.35),
]


def parse_sizes(raw: str) -> list[float]:
    return [float(value) for value in raw.split(",") if value.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark the chunkers.")
    parser.add_argument("--sizes", default="0.0625,0.5,4,32", help="corpus sizes in MB")
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--json", default="", help="write full results to this path")
    parser.add_argument("--keep-corpus", action="store_true")
    args = parser.parse_args()

    bootstrap_django()
    from documents.ingestion import _chunk_text, find_cpp_chunker, run_cpp_chunker

    binary = find_cpp_chunker()
    if binary is None:
        print("C++ chunker not found. Build it first with: make cpp-build")
        raise SystemExit(1)
    print(f"C++ binary: {binary}")

    def run_python(path: Path):
        started = time.perf_counter()
        # Decode from bytes exactly like ingest_bytes. Path.read_text applies
        # universal-newline translation, which would hide CRLF byte offsets.
        text = path.read_bytes().decode("utf-8", errors="replace")
        chunks = _chunk_text(
            text,
            page=None,
            start_index=0,
            chunk_size=CHUNK_SIZE,
            overlap=OVERLAP,
            include_byte_offsets=True,
        )
        return time.perf_counter() - started, chunks

    def run_pipeline(path: Path):
        # Production path: subprocess spawn plus binary record decoding
        started = time.perf_counter()
        chunks = run_cpp_chunker(path, 0, CHUNK_SIZE, OVERLAP)
        return time.perf_counter() - started, chunks

    def run_binary(path: Path):
        # Binary alone, output discarded, isolates transport cost
        started = time.perf_counter()
        subprocess.run(
            [
                str(binary),
                "--input",
                str(path),
                "--chunk-size",
                str(CHUNK_SIZE),
                "--overlap",
                str(OVERLAP),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        return time.perf_counter() - started, None

    cases = [(f"lf_{size:g}MB", size, "\n", 0.0) for size in parse_sizes(args.sizes)]
    cases.extend(CASES)

    corpus_dir = Path(tempfile.mkdtemp(prefix="chunker_bench_"))
    results = []
    header = (
        f"{'case':<16}{'bytes':>11}{'python ms':>11}{'cpp ms':>11}"
        f"{'binary ms':>11}{'ratio':>8}{'same':>7}{'offsets':>12}"
    )
    print(header)
    print("-" * len(header))
    try:
        for name, megabytes, newline, unicode_ratio in cases:
            path = build_corpus(
                corpus_dir / f"{name}.txt",
                int(megabytes * 1024 * 1024),
                newline,
                unicode_ratio,
            )
            size = path.stat().st_size
            runs = args.runs if size < 2 * 1024 * 1024 else max(3, args.runs // 2)

            python_timing, python_chunks = measure(run_python, path, runs)
            cpp_timing, cpp_chunks = measure(run_pipeline, path, runs)
            binary_timing, _ = measure(run_binary, path, runs)
            quality = compare_chunks(python_chunks, cpp_chunks)

            entry = {
                "case": name,
                "bytes": size,
                "python": python_timing,
                "cpp_pipeline": cpp_timing,
                "cpp_binary_only": binary_timing,
                "ratio": python_timing["median_ms"] / cpp_timing["median_ms"],
                "python_mb_per_s": (size / 1048576)
                / (python_timing["median_ms"] / 1000),
                "cpp_mb_per_s": (size / 1048576) / (cpp_timing["median_ms"] / 1000),
                "quality": quality,
                "cpp_offsets": offsets_round_trip(cpp_chunks, path, newline),
                "python_offsets": offsets_round_trip(python_chunks, path, newline),
            }
            results.append(entry)
            print(
                f"{name:<16}{size:>11}{python_timing['median_ms']:>11.2f}"
                f"{cpp_timing['median_ms']:>11.2f}{binary_timing['median_ms']:>11.2f}"
                f"{entry['ratio']:>7.2f}x{str(quality['identical']):>7}"
                f"{entry['cpp_offsets']:>12}"
            )
    finally:
        if not args.keep_corpus:
            shutil.rmtree(corpus_dir, ignore_errors=True)

    print()
    print("ratio > 1.00x means the C++ path is faster than the Python path.")
    print("offsets shows how many chunks address the raw file correctly.")
    print("This is a chunker-pipeline measurement, not end-to-end ingestion.")
    for entry in results:
        if entry["python_offsets"] != entry["cpp_offsets"]:
            print(
                f"note: {entry['case']} python offsets {entry['python_offsets']}, "
                f"cpp offsets {entry['cpp_offsets']}"
            )

    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"wrote {args.json}")


if __name__ == "__main__":
    main()
