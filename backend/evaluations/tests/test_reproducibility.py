"""Evaluation reproducibility: strategy labeling, identity, and persistence.

Every test here uses fake generators and judges, so no live model is called.
"""

from __future__ import annotations

import json

import pytest
from documents.models import Collection, Document, DocumentChunk

from evaluations.harness import (
    corpus_fingerprint,
    evaluation_identity,
    load_questions,
    question_set_fingerprint,
    run_evaluation,
)
from evaluations.models import EvaluationRun
from evaluations.runs import record_evaluation_run


class FakeJudge:
    model = "fake-local-judge"

    def judge(self, question, answer, context, expected_terms):
        return {"score": 1.0, "rationale": "Deterministic test score."}


def fake_generator(question, retrieved):
    return "Deterministic answer. [1]"


class FakeEmbeddingProvider:
    def embed_query(self, text):
        return [0.1, 0.2, 0.3]

    def embed_documents(self, texts):
        return [[0.1, 0.2, 0.3] for _ in texts]


@pytest.fixture
def corpus():
    collection = Collection.objects.create(name="Demo")
    guide = Document.objects.create(
        collection=collection,
        title="deployment_guide.md",
        original_filename="deployment_guide.md",
        file_type="md",
        sha256="d" * 64,
    )
    DocumentChunk.objects.create(
        document=guide,
        chunk_index=0,
        text="Validate database migrations and cache connectivity before deployment.",
    )
    return guide


def run(questions, **kwargs):
    return run_evaluation(
        questions,
        answer_generator=fake_generator,
        answer_judge=FakeJudge(),
        **kwargs,
    )


@pytest.mark.django_db
def test_vector_request_that_falls_back_is_labeled_bm25(corpus):
    metrics = run(
        [
            {
                "question": "What should be validated?",
                "expected_document": "deployment_guide.md",
            }
        ],
        mode="vector",
    )

    assert metrics.requested_mode == "vector"
    assert metrics.retrieval_strategy == "bm25"
    assert "disabled" in metrics.fallback_reason
    assert metrics.retrieval_strategy_counts == {"bm25": 1}
    assert metrics.results[0].retrieval_strategy == "bm25"


@pytest.mark.django_db
def test_mode_comparison_cannot_silently_report_bm25_as_vector(corpus):
    vector_run = run([{"question": "validate migrations"}], mode="vector")
    hybrid_run = run([{"question": "validate migrations"}], mode="hybrid")

    # Both requested modes fell back to the same algorithm; the labels say so.
    assert vector_run.requested_mode != hybrid_run.requested_mode
    assert vector_run.retrieval_strategy == hybrid_run.retrieval_strategy == "bm25"


@pytest.mark.django_db
def test_unrelated_questions_score_no_results_precision(corpus):
    metrics = run(
        [
            {
                "question": "validate migrations",
                "expected_document": "deployment_guide.md",
            },
            {"question": "orbital period of Enceladus", "expect_no_results": True},
            {"question": "sweetest persimmon cultivar", "expect_no_results": True},
        ]
    )

    assert metrics.no_results_question_count == 2
    assert metrics.no_results_precision == 1.0
    # Unrelated rows never enter the recall or coverage denominators.
    assert metrics.labeled_question_count == 1
    assert metrics.coverage_question_count == 1


@pytest.mark.django_db
def test_no_results_precision_falls_when_retrieval_answers_everything(corpus):
    metrics = run(
        [
            {"question": "validate migrations", "expect_no_results": True},
            {"question": "orbital period of Enceladus", "expect_no_results": True},
        ]
    )

    assert metrics.no_results_precision == 0.5


@pytest.mark.django_db
def test_corpus_fingerprint_tracks_document_identity(corpus):
    first_hash, count = corpus_fingerprint()
    assert count == 1

    Document.objects.create(
        collection=corpus.collection,
        title="extra.md",
        original_filename="extra.md",
        file_type="md",
        sha256="e" * 64,
    )
    second_hash, second_count = corpus_fingerprint()

    assert second_count == 2
    assert second_hash != first_hash


def test_question_set_fingerprint_ignores_key_order():
    left = [{"question": "a", "expected_document": "x.md"}]
    right = [{"expected_document": "x.md", "question": "a"}]

    assert question_set_fingerprint(left) == question_set_fingerprint(right)
    assert question_set_fingerprint(left) != question_set_fingerprint(
        [{"question": "b"}]
    )


@pytest.mark.django_db
def test_recorded_run_persists_configuration_and_identity(corpus, tmp_path):
    questions = [
        {"question": "validate migrations", "expected_document": "deployment_guide.md"}
    ]
    questions_path = tmp_path / "questions.json"
    questions_path.write_text(json.dumps(questions), encoding="utf-8")
    identity = evaluation_identity(questions, questions_path)
    metrics = run(questions, mode="vector", top_k=3, rerank=False)

    stored = record_evaluation_run("Recorded run", metrics, identity)

    stored.refresh_from_db()
    assert stored.retrieval_mode == "vector"
    assert stored.retrieval_strategy == "bm25"
    assert stored.fallback_reason
    assert stored.top_k == 3
    assert stored.rerank is False
    assert stored.embedding_model
    assert stored.llm_model
    assert stored.corpus_hash == identity.corpus_hash
    assert stored.corpus_document_count == 1
    assert stored.chunk_hash == identity.chunk_hash
    assert stored.corpus_chunk_count == identity.corpus_chunk_count
    assert stored.question_set_hash == identity.question_set_hash
    assert stored.question_set_path == str(questions_path)
    assert stored.config["retrieval_strategy_counts"] == {"bm25": 1}
    assert EvaluationRun.objects.count() == 1


@pytest.mark.django_db
def test_shipped_eval_question_set_is_loadable_and_labeled():
    from pathlib import Path

    path = Path(__file__).resolve().parents[3] / "data" / "eval_questions.json"
    questions = load_questions(path)

    kinds = {}
    for question in questions:
        kinds[question["kind"]] = kinds.get(question["kind"], 0) + 1
    assert kinds == {
        "relevant": 6,
        "paraphrased": 4,
        "ambiguous": 3,
        "unrelated": 3,
    }
    unrelated = [q for q in questions if q["kind"] == "unrelated"]
    assert all(q["expect_no_results"] for q in unrelated)
    assert all("expected_document" not in q for q in unrelated)
    labeled = [q for q in questions if q.get("expected_document")]
    assert len(labeled) == 10


@pytest.mark.django_db
def test_shipped_eval_corpus_files_exist_for_every_label():
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    questions = load_questions(root / "data" / "eval_questions.json")
    for question in questions:
        expected = question.get("expected_document")
        if expected:
            assert (root / "data" / "eval_corpus" / expected).exists()
