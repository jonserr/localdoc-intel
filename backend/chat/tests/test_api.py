import pytest
from django.urls import reverse
from documents.models import Collection, Document, DocumentChunk


@pytest.fixture
def indexed_chunk():
    collection = Collection.objects.create(name="Platform")
    document = Document.objects.create(
        collection=collection,
        title="Deployment Guide",
        original_filename="deployment_guide.md",
        file_type="md",
        sha256="b" * 64,
        status=Document.Status.INDEXED,
        chunk_count=1,
        byte_size=256,
    )
    return DocumentChunk.objects.create(
        document=document,
        chunk_index=0,
        text="Before deployment, validate migrations and cache connectivity.",
        start_line=10,
        end_line=12,
    )


@pytest.mark.django_db
def test_chat_query_returns_cited_answer(client, indexed_chunk):
    response = client.post(
        reverse("chat-query"),
        data={
            "question": "What validates deployment?",
            "collection": "Platform",
            "retrieval_mode": "hybrid",
            "top_k": 3,
            "rerank": True,
        },
        content_type="application/json",
    )

    assert response.status_code == 200
    payload = response.json()
    assert "answer" in payload
    assert payload["metadata"]["retrieval_top_k"] == 3
    assert payload["metadata"]["rerank"] is True
    assert payload["citations"][0]["chunk_id"] == indexed_chunk.id


@pytest.mark.django_db
def test_chat_query_rejects_unknown_collection(client):
    response = client.post(
        reverse("chat-query"),
        data={"question": "What is indexed?", "collection": "Missing"},
        content_type="application/json",
    )

    assert response.status_code == 400
    assert "collection" in response.json()


@pytest.mark.django_db
def test_chat_query_rejects_invalid_top_k(client):
    response = client.post(
        reverse("chat-query"),
        data={"question": "What is indexed?", "top_k": 0},
        content_type="application/json",
    )

    assert response.status_code == 400
    assert "top_k" in response.json()


@pytest.mark.django_db
def test_chat_history_filters(client, indexed_chunk):
    client.post(
        reverse("chat-query"),
        data={
            "question": "What validates deployment?",
            "collection": "Platform",
            "retrieval_mode": "hybrid",
        },
        content_type="application/json",
    )

    response = client.get(reverse("chat-history"), {"retrieval_mode": "hybrid"})

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["collection"] == "Platform"


@pytest.mark.django_db
def test_chat_history_rejects_invalid_retrieval_mode(client):
    response = client.get(reverse("chat-history"), {"retrieval_mode": "bad"})

    assert response.status_code == 400
    assert "retrieval_mode" in response.json()


@pytest.mark.django_db
def test_unrelated_question_returns_no_results_and_no_citations(client, indexed_chunk):
    response = client.post(
        reverse("chat-query"),
        data={"question": "platypus astronomy", "retrieval_mode": "hybrid"},
        content_type="application/json",
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["citations"] == []
    assert payload["metadata"]["answer_mode"] == "no_results"
    assert "No relevant passages" in payload["answer"]


@pytest.mark.django_db
def test_chat_query_exposes_citation_validation(
    client, indexed_chunk, settings, monkeypatch
):
    settings.ANSWER_GENERATION_ENABLED = True

    class Provider:
        model = "fake-model"

        def generate(self, question, context):
            return "Validate migrations [1]."

    monkeypatch.setattr("chat.generation.OllamaGenerationProvider", Provider)

    response = client.post(
        reverse("chat-query"),
        data={"question": "What validates deployment?", "collection": "Platform"},
        content_type="application/json",
    )

    payload = response.json()
    assert payload["metadata"]["answer_mode"] == "generated"
    assert payload["metadata"]["citation_status"] == "valid"
    assert payload["metadata"]["cited_sources"] == [1]
    assert payload["metadata"]["invalid_citations"] == []
