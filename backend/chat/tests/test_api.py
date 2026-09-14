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
    monkeypatch.setattr("chat.views.inventory_target", lambda question, scope: None)

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


@pytest.mark.django_db
@pytest.mark.parametrize("collection", ["Platform", "platform", ""])
@pytest.mark.parametrize("question, source_count", [("deployment", 1), ("platypus", 0)])
def test_chat_coverage_matches_search_scope(
    client, indexed_chunk, collection, question, source_count, settings, mocker
):
    # Unmatched chunks still belong to the scope; multiple chunks are not
    # multiple documents. Another collection must only count in an all-scope query.
    DocumentChunk.objects.create(
        document=indexed_chunk.document, chunk_index=1, text="Unrelated content."
    )
    other = Document.objects.create(
        collection=Collection.objects.create(name="Other"),
        title="Other document",
        original_filename="other.txt",
        file_type="txt",
        sha256="d" * 64,
    )
    DocumentChunk.objects.create(document=other, chunk_index=0, text="Other content.")
    settings.ANSWER_GENERATION_ENABLED = True
    mocker.patch("chat.views.inventory_target", return_value=None)
    provider = mocker.Mock(model="fake-model")
    provider.generate.return_value = "Validate migrations [1]."
    mocker.patch("chat.generation.OllamaGenerationProvider", return_value=provider)

    response = client.post(
        reverse("chat-query"),
        data={"question": question, "collection": collection, "top_k": 5},
        content_type="application/json",
    )

    assert response.status_code == 200
    payload = response.json()
    metadata = payload["metadata"]
    documents, chunks = (1, 2) if collection else (2, 3)
    assert (
        metadata["retrieved_source_count"] == source_count == len(payload["citations"])
    )
    assert metadata["collection_document_count"] == documents
    assert metadata["collection_chunk_count"] == chunks
    assert metadata["retrieval_top_k"] == 5
    if source_count:
        context = provider.generate.call_args.args[1]
        assert f"Retrieved sources supplied: {source_count} chunks." in context
        assert f"Documents in the searched collection(s): {documents}." in context
        assert f"Chunks in the searched collection(s): {chunks}." in context
    else:
        provider.generate.assert_not_called()
        assert metadata["answer_mode"] == "no_results"
