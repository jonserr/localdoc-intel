#!/usr/bin/env python
"""Benchmark retrieval latency across modes using the demo question set.

Usage:
    python scripts/benchmark_retrieval.py [--top-k 5] [--runs 3]
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
import time
from pathlib import Path


def bootstrap_django() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    for candidate in (repo_root / "backend", Path("/app")):
        if candidate.exists():
            sys.path.insert(0, str(candidate))
            break
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django

    django.setup()


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark retrieval latency.")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args()

    bootstrap_django()
    from evaluations.harness import default_questions_path, load_questions
    from retrieval.services import retrieve_chunks

    questions = load_questions(default_questions_path())
    for mode in ("hybrid", "metadata-filtered", "vector"):
        latencies = []
        for _ in range(args.runs):
            for row in questions:
                started = time.perf_counter()
                retrieve_chunks(row["question"], top_k=args.top_k, mode=mode)
                latencies.append((time.perf_counter() - started) * 1000)
        print(
            f"{mode:>18}: mean {statistics.mean(latencies):7.1f}ms  "
            f"median {statistics.median(latencies):7.1f}ms  "
            f"p95 {sorted(latencies)[int(len(latencies) * 0.95) - 1]:7.1f}ms  "
            f"({len(latencies)} queries)"
        )


if __name__ == "__main__":
    main()
