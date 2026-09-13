"""A mode label must not hide fallback or mix distinct query scopes."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "benchmark_retrieval.py"
spec = importlib.util.spec_from_file_location("benchmark_retrieval", SCRIPT)
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


def test_report_exposes_mixed_strategies_and_fallback_reasons(capsys):
    calls = []
    outcomes = iter(
        [
            SimpleNamespace(strategy="vector", fallback_reason="", chunks=[object()]),
            SimpleNamespace(
                strategy="bm25", fallback_reason="vector search failed", chunks=[]
            ),
        ]
    )
    ticks = iter([0.0, 0.01, 0.1, 0.12])

    def retrieve(question, **kwargs):
        calls.append((question, kwargs))
        return next(outcomes)

    result = benchmark.benchmark_mode(
        [
            {"question": "first", "collection": "A"},
            {"question": "second", "collection": "B"},
        ],
        "vector",
        3,
        1,
        retrieve,
        clock=lambda: next(ticks),
    )
    assert result["requested_mode"] == "vector"
    assert result["strategy_counts"] == {"bm25": 1, "vector": 1}
    assert result["fallback_reason_counts"] == {"vector search failed": 1}
    assert result["no_results_count"] == 1
    assert result["median_ms"] == pytest.approx(15)
    assert result["p95_ms"] == pytest.approx(20)
    assert [c[1]["collection"] for c in calls] == ["A", "B"]
    benchmark.print_report(result)
    output = capsys.readouterr().out
    assert '"bm25": 1' in output
    assert "fallback (1 queries): vector search failed" in output


def test_override_collection_rerank_and_repeat_count():
    calls = []

    def retrieve(question, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(strategy="bm25", fallback_reason="disabled", chunks=[])

    result = benchmark.benchmark_mode(
        [{"question": "test", "collection": "original"}],
        "hybrid",
        5,
        3,
        retrieve,
        collection="Eval Corpus",
        rerank=True,
    )
    assert result["query_count"] == 3
    assert result["strategy_counts"] == {"bm25": 3}
    assert all(c["collection"] == "Eval Corpus" and c["rerank"] for c in calls)


@pytest.mark.parametrize(
    "questions,runs,top_k", [([], 1, 5), ([{}], 0, 5), ([{}], 1, 0)]
)
def test_empty_benchmarks_are_rejected(questions, runs, top_k):
    with pytest.raises(ValueError):
        benchmark.benchmark_mode(questions, "vector", top_k, runs, lambda: None)
