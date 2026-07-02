from types import SimpleNamespace

import pytest
from django.urls import reverse
from documents.models import Collection, Document, DocumentChunk


@pytest.fixture
def demo_document():
    collection = Collection.objects.create(name="Demo")
    document = Document.objects.create(
        collection=collection,
        title="deployment_guide.md",
        original_filename="deployment_guide.md",
        file_type="md",
        sha256="a" * 64,
        status=Document.Status.INDEXED,
        chunk_count=1,
        byte_size=256,
    )
    DocumentChunk.objects.create(
        document=document,
        chunk_index=0,
        text=(
            "Before deployment, validate database migrations, cache "
            "connectivity, health endpoints, and queue workers. If validation "
            "fails, halt promotion and attach logs."
        ),
    )
    return document


def fake_metrics(question_count: int = 1):
    return SimpleNamespace(
        recall_at_k=1.0,
        mean_reciprocal_rank=1.0,
        citation_coverage=1.0,
        groundedness_score=1.0,
        average_latency_ms=12,
        question_count=question_count,
        answer_quality_score=0.7,
        judged_answer_count=question_count,
        answer_judge_model="fake-local-judge",
    )


@pytest.mark.django_db
def test_evaluation_run_computes_metrics(client, demo_document, monkeypatch):
    monkeypatch.setattr(
        "evaluations.views.run_evaluation",
        lambda questions, **kwargs: fake_metrics(len(questions)),
    )

    response = client.post(
        reverse("evaluation-run"),
        data={"name": "Smoke test"},
        content_type="application/json",
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["name"] == "Smoke test"
    assert payload["question_count"] > 0
    assert 0 <= payload["recall_at_k"] <= 1
    assert payload["answer_quality_score"] == pytest.approx(0.7)


@pytest.mark.django_db
def test_evaluation_list(client, demo_document, monkeypatch):
    monkeypatch.setattr(
        "evaluations.views.run_evaluation",
        lambda questions, **kwargs: fake_metrics(len(questions)),
    )

    client.post(
        reverse("evaluation-run"),
        data={"name": "Smoke test"},
        content_type="application/json",
    )

    response = client.get(reverse("evaluation-list"))

    assert response.status_code == 200
    assert response.json()[0]["name"] == "Smoke test"


@pytest.mark.django_db
def test_evaluation_run_rejects_blank_name(client):
    response = client.post(
        reverse("evaluation-run"),
        data={"name": ""},
        content_type="application/json",
    )

    assert response.status_code == 400
    assert "name" in response.json()


@pytest.mark.django_db
def test_evaluation_run_always_judges_answers(client, demo_document, monkeypatch):
    captured = {}

    def fake_run_evaluation(questions, **kwargs):
        captured.update(kwargs)
        return fake_metrics(question_count=len(questions))

    monkeypatch.setattr("evaluations.views.run_evaluation", fake_run_evaluation)

    response = client.post(
        reverse("evaluation-run"),
        data={"name": "Judged smoke test"},
        content_type="application/json",
    )

    assert response.status_code == 201
    payload = response.json()
    assert "judge_answers" not in captured
    assert payload["answer_quality_score"] == pytest.approx(0.7)
    assert payload["judged_answer_count"] == payload["question_count"]
    assert payload["answer_judge_model"] == "fake-local-judge"
