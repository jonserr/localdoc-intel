#!/usr/bin/env python
"""Measure retrieval latency and report the strategy that actually ran.

Usage:
    python scripts/benchmark_retrieval.py --runs 3 --top-k 5
    python scripts/benchmark_retrieval.py --questions data/eval_questions.json \
        --collection 'Eval Corpus' --json results.json
"""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
import time
from collections import Counter
from collections.abc import Callable
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


def positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def benchmark_mode(
    questions: list[dict],
    mode: str,
    top_k: int,
    runs: int,
    retrieve_fn: Callable,
    *,
    collection: str | None = None,
    rerank: bool = False,
    clock: Callable[[], float] = time.perf_counter,
) -> dict:
    if not questions or runs < 1 or top_k < 1:
        raise ValueError("questions, runs, and top_k must be nonempty/positive")
    latencies = []
    strategies: Counter[str] = Counter()
    fallbacks: Counter[str] = Counter()
    empty_results = 0
    for _ in range(runs):
        for row in questions:
            started = clock()
            outcome = retrieve_fn(
                row["question"],
                collection=(
                    collection if collection is not None else row.get("collection")
                ),
                top_k=top_k,
                mode=mode,
                rerank=rerank,
            )
            latencies.append((clock() - started) * 1000)
            strategies[outcome.strategy] += 1
            if outcome.fallback_reason:
                fallbacks[outcome.fallback_reason] += 1
            empty_results += not outcome.chunks
    return {
        "requested_mode": mode,
        "top_k": top_k,
        "rerank": rerank,
        "query_count": len(latencies),
        "question_count": len(questions),
        "runs": runs,
        "collection": collection,
        "strategy_counts": dict(sorted(strategies.items())),
        "fallback_reason_counts": dict(sorted(fallbacks.items())),
        "no_results_count": empty_results,
        "mean_ms": statistics.mean(latencies),
        "median_ms": statistics.median(latencies),
        "p95_ms": sorted(latencies)[math.ceil(len(latencies) * 0.95) - 1],
    }


def print_report(result: dict) -> None:
    print(
        f"{result['requested_mode']:>18}: mean {result['mean_ms']:7.1f}ms  "
        f"median {result['median_ms']:7.1f}ms  p95 {result['p95_ms']:7.1f}ms  "
        f"({result['query_count']} queries; {result['no_results_count']} empty)"
    )
    print("  actual strategies: " + json.dumps(result["strategy_counts"]))
    for reason, count in result["fallback_reason_counts"].items():
        print(f"  fallback ({count} queries): {reason}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--top-k", type=positive_int, default=5)
    parser.add_argument("--runs", type=positive_int, default=3)
    parser.add_argument("--questions", type=Path)
    parser.add_argument("--collection")
    parser.add_argument("--rerank", action="store_true")
    parser.add_argument("--json", type=Path, help="write the complete measured report")
    args = parser.parse_args()

    bootstrap_django()
    from evaluations.harness import default_questions_path, load_questions
    from retrieval.services import retrieve

    questions_path = args.questions or default_questions_path()
    questions = load_questions(questions_path)
    results = []
    for mode in ("hybrid", "metadata-filtered", "vector"):
        result = benchmark_mode(
            questions,
            mode,
            args.top_k,
            args.runs,
            retrieve,
            collection=args.collection,
            rerank=args.rerank,
        )
        print_report(result)
        results.append(result)
    if args.json:
        args.json.write_text(
            json.dumps(
                {"questions_path": str(questions_path), "results": results}, indent=2
            )
            + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
