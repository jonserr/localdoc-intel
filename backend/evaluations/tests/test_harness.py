import json
from types import SimpleNamespace

import pytest
from documents.models import Collection, Document, DocumentChunk

from evaluations.harness import (
    EvaluationInputError,
    default_questions_path,
    load_questions,
    run_evaluation,
)


@pytest.fixture
def indexed_documents():
    collection = Collection.objects.create(name="Demo")
    guide = Document.objects.create(
        collection=collection,
        title="deployment_guide.md",
        original_filename="deployment_guide.md",
        file_type="md",
        sha256="d" * 64,
        status=Document.Status.INDEXED,
        chunk_count=1,
        byte_size=256,
    )
    DocumentChunk.objects.create(
        document=guide,
        chunk_index=0,
        text=(
            "Before deployment, validate database migrations, cache "
            "connectivity, health endpoints, and queue workers."
        ),
    )
    policy = Document.objects.create(
        collection=collection,
        title="security_policy.md",
        original_filename="security_policy.md",
        file_type="md",
        sha256="e" * 64,
        status=Document.Status.INDEXED,
        chunk_count=1,
        byte_size=256,
    )
    DocumentChunk.objects.create(
        document=policy,
        chunk_index=0,
        text="Service credentials must be rotated every 90 days.",
    )
    return guide, policy


def test_load_questions_missing_file(tmp_path):
    with pytest.raises(EvaluationInputError, match="not found"):
        load_questions(tmp_path / "missing.json")


def test_load_questions_invalid_json(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(EvaluationInputError, match="Invalid JSON"):
        load_questions(path)


def test_load_questions_accepts_open_demo_questions(tmp_path):
    path = tmp_path / "incomplete.json"
    path.write_text(json.dumps([{"question": "Only a question"}]), encoding="utf-8")
    assert load_questions(path) == [{"question": "Only a question"}]


def test_default_questions_path_resolves_repo_file():
    assert default_questions_path().exists()


@pytest.mark.django_db
def test_run_evaluation_computes_metrics(indexed_documents):
    class FakeJudge:
        model = "fake-local-judge"

        def judge(self, question, answer, context, expected_terms):
            return {"score": 1.0, "rationale": "Deterministic test score."}

    def fake_answer_generator(question, retrieved):
        return "Deterministic answer for evaluation tests. [1]"

    questions = [
        {
            "question": "What should be validated before deployment?",
            "expected_document": "deployment_guide.md",
            "expected_terms": ["migrations", "cache"],
        },
        {
            "question": "How often are credentials rotated?",
            "expected_document": "security_policy.md",
            "expected_terms": ["90 days"],
        },
        {
            "question": "What color is the moon?",
            "expected_document": "astronomy.md",
            "expected_terms": ["basalt"],
        },
    ]

    metrics = run_evaluation(
        questions,
        top_k=5,
        mode="hybrid",
        rerank=True,
        answer_generator=fake_answer_generator,
        answer_judge=FakeJudge(),
    )

    assert metrics.question_count == 3
    assert metrics.recall_at_k == pytest.approx(2 / 3)
    assert metrics.mean_reciprocal_rank == pytest.approx(2 / 3)
    assert metrics.citation_coverage == pytest.approx(2 / 3)
    assert metrics.groundedness_score == pytest.approx(2 / 3)
    assert metrics.average_latency_ms >= 0
    assert metrics.judged_answer_count == 3
    assert metrics.answer_quality_score == pytest.approx(1.0)
    assert metrics.results[0].hit is True
    assert metrics.results[2].hit is False


@pytest.mark.django_db
def test_run_evaluation_can_judge_answer_quality(indexed_documents):
    class FakeJudge:
        model = "fake-local-judge"

        def judge(self, question, answer, context, expected_terms):
            assert "What should be validated" in question
            assert "migrations" in answer
            assert "database migrations" in context
            assert expected_terms == ["migrations", "cache"]
            return {"score": 0.8, "rationale": "Answer covers the key terms."}

    def fake_answer_generator(question, retrieved):
        return "Validate migrations and cache connectivity before deployment. [1]"

    questions = [
        {
            "question": "What should be validated before deployment?",
            "expected_document": "deployment_guide.md",
            "expected_terms": ["migrations", "cache"],
        }
    ]

    metrics = run_evaluation(
        questions,
        top_k=5,
        mode="hybrid",
        rerank=True,
        answer_generator=fake_answer_generator,
        answer_judge=FakeJudge(),
    )

    assert metrics.judged_answer_count == 1
    assert metrics.answer_quality_score == pytest.approx(0.8)
    assert metrics.answer_judge_model == "fake-local-judge"
    assert metrics.results[0].answer_quality_score == pytest.approx(0.8)
    assert metrics.results[0].answer == (
        "Validate migrations and cache connectivity before deployment. [1]"
    )


@pytest.mark.django_db
def test_run_eval_command_creates_run(indexed_documents, tmp_path, monkeypatch):
    from django.core.management import call_command

    from evaluations.models import EvaluationRun

    def fake_run_evaluation(questions, **kwargs):
        return SimpleNamespace(
            question_count=len(questions),
            recall_at_k=1.0,
            mean_reciprocal_rank=1.0,
            citation_coverage=1.0,
            groundedness_score=1.0,
            average_latency_ms=25,
            top_k=kwargs["top_k"],
            answer_quality_score=0.9,
            judged_answer_count=1,
            answer_judge_model="fake-local-judge",
            results=[
                SimpleNamespace(
                    hit=True,
                    question="What should be validated before deployment?",
                    expected_document="deployment_guide.md",
                    retrieved_documents=["deployment_guide.md"],
                    term_coverage=1.0,
                    latency_ms=25,
                )
            ],
        )

    monkeypatch.setattr(
        "evaluations.management.commands.run_eval.run_evaluation",
        fake_run_evaluation,
    )
    questions_path = tmp_path / "questions.json"
    questions_path.write_text(
        json.dumps(
            [
                {
                    "question": "What should be validated before deployment?",
                    "expected_document": "deployment_guide.md",
                    "expected_terms": ["migrations"],
                }
            ]
        ),
        encoding="utf-8",
    )

    call_command("run_eval", "--questions", str(questions_path), "--name", "CI run")

    run = EvaluationRun.objects.get(name="CI run")
    assert run.question_count == 1
    assert run.recall_at_k == 1.0
    assert run.answer_quality_score == pytest.approx(0.9)
    assert run.judged_answer_count == 1


@pytest.mark.django_db
def test_run_eval_command_always_judges_answers(
    indexed_documents, tmp_path, monkeypatch
):
    from django.core.management import call_command

    from evaluations.models import EvaluationRun

    captured = {}

    def fake_run_evaluation(questions, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            question_count=len(questions),
            recall_at_k=1.0,
            mean_reciprocal_rank=1.0,
            citation_coverage=1.0,
            groundedness_score=1.0,
            average_latency_ms=25,
            top_k=kwargs["top_k"],
            answer_quality_score=0.9,
            judged_answer_count=1,
            answer_judge_model="fake-local-judge",
            results=[
                SimpleNamespace(
                    hit=True,
                    question="What should be validated before deployment?",
                    expected_document="deployment_guide.md",
                    retrieved_documents=["deployment_guide.md"],
                    term_coverage=1.0,
                    latency_ms=25,
                )
            ],
        )

    monkeypatch.setattr(
        "evaluations.management.commands.run_eval.run_evaluation",
        fake_run_evaluation,
    )
    questions_path = tmp_path / "questions.json"
    questions_path.write_text(
        json.dumps(
            [
                {
                    "question": "What should be validated before deployment?",
                    "expected_document": "deployment_guide.md",
                    "expected_terms": ["migrations"],
                }
            ]
        ),
        encoding="utf-8",
    )

    call_command(
        "run_eval",
        "--questions",
        str(questions_path),
        "--name",
        "Judged CI run",
    )

    run = EvaluationRun.objects.get(name="Judged CI run")
    assert "judge_answers" not in captured
    assert run.answer_quality_score == pytest.approx(0.9)
    assert run.judged_answer_count == 1
    assert run.answer_judge_model == "fake-local-judge"


@pytest.mark.django_db
def test_run_evaluation_retrieval_only_skips_llm_calls(indexed_documents):
    def failing_generator(question, retrieved):
        raise AssertionError("generation must not run in retrieval-only mode")

    class FailingJudge:
        model = "fake-local-judge"

        def judge(self, question, answer, context, expected_terms):
            raise AssertionError("judging must not run in retrieval-only mode")

    questions = [
        {
            "question": "What should be validated before deployment?",
            "expected_document": "deployment_guide.md",
            "expected_terms": ["migrations"],
        }
    ]

    metrics = run_evaluation(
        questions,
        top_k=5,
        mode="hybrid",
        rerank=True,
        answer_generator=failing_generator,
        answer_judge=FailingJudge(),
        retrieval_only=True,
    )

    assert metrics.recall_at_k == 1.0
    assert metrics.judged_answer_count == 0
    assert metrics.results[0].answer == ""
    assert metrics.results[0].answer_quality_score is None
    assert metrics.results[0].generation_ms == 0
    assert metrics.results[0].judge_ms == 0


@pytest.mark.django_db
def test_run_evaluation_reports_stage_progress(indexed_documents):
    class FakeJudge:
        model = "fake-local-judge"

        def judge(self, question, answer, context, expected_terms):
            return {"score": 0.9, "rationale": "ok"}

    events = []

    def progress(state, row, index, total, payload):
        events.append(state)

    run_evaluation(
        [
            {
                "question": "What should be validated before deployment?",
                "expected_document": "deployment_guide.md",
            }
        ],
        answer_generator=lambda question, retrieved: "Answer [1]",
        answer_judge=FakeJudge(),
        progress_callback=progress,
    )

    assert events == ["start", "retrieved", "generated", "judged", "done"]
