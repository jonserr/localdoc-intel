import pytest
from django.urls import reverse

from documents.models import Collection, Document, DocumentChunk


@pytest.fixture
def indexed_document():
    collection = Collection.objects.create(name="Platform", description="Runbooks")
    document = Document.objects.create(
        collection=collection,
        title="Deployment Guide",
        original_filename="deployment_guide.md",
        file_type="md",
        sha256="a" * 64,
        status=Document.Status.INDEXED,
        chunk_count=2,
        byte_size=512,
    )
    DocumentChunk.objects.create(
        document=document,
        chunk_index=0,
        text="Validate migrations and health endpoints before deployment.",
        start_line=1,
        end_line=4,
        byte_start=0,
        byte_end=64,
        token_count=8,
    )
    DocumentChunk.objects.create(
        document=document,
        chunk_index=1,
        text="Attach logs if validation fails.",
        start_line=5,
        end_line=8,
        byte_start=65,
        byte_end=120,
        token_count=5,
    )
    return document


@pytest.mark.django_db
def test_health_endpoint(client):
    response = client.get(reverse("health"))

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["database"] == "ok"


@pytest.mark.django_db
def test_stats_endpoint_empty(client):
    response = client.get(reverse("stats"))

    assert response.status_code == 200
    assert response.json()["total_documents"] == 0
    assert response.json()["latest_document"] is None


@pytest.mark.django_db
def test_stats_endpoint_with_documents(client, indexed_document):
    response = client.get(reverse("stats"))

    payload = response.json()
    assert response.status_code == 200
    assert payload["total_documents"] == 1
    assert payload["total_chunks"] == 2
    assert payload["total_collections"] == 1
    assert payload["documents_by_status"]["indexed"] == 1
    assert payload["documents_by_file_type"]["md"] == 1
    assert payload["latest_document"]["id"] == indexed_document.id


@pytest.mark.django_db
def test_document_list_filters(client, indexed_document):
    response = client.get(
        reverse("document-list"),
        {"collection": "platform", "file_type": ".MD", "status": "indexed"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["id"] == indexed_document.id
    assert payload[0]["collection"]["name"] == "Platform"


@pytest.mark.django_db
def test_document_list_invalid_status_returns_400(client):
    response = client.get(reverse("document-list"), {"status": "unknown"})

    assert response.status_code == 400
    assert "status" in response.json()


@pytest.mark.django_db
def test_document_detail(client, indexed_document):
    response = client.get(reverse("document-detail", args=[indexed_document.id]))

    assert response.status_code == 200
    assert response.json()["title"] == "Deployment Guide"


@pytest.mark.django_db
def test_document_nested_chunks(client, indexed_document):
    response = client.get(reverse("document-chunks", args=[indexed_document.id]))

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 2
    assert payload[0]["document_title"] == "Deployment Guide"
    assert payload[0]["text_preview"].startswith("Validate migrations")


@pytest.mark.django_db
def test_chunk_list_filters(client, indexed_document):
    response = client.get(
        reverse("chunk-list"),
        {"document_id": indexed_document.id, "search": "logs"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["chunk_index"] == 1


@pytest.mark.django_db
def test_chunk_list_invalid_document_id_returns_400(client):
    response = client.get(reverse("chunk-list"), {"document_id": "bad"})

    assert response.status_code == 400
    assert "document_id" in response.json()


@pytest.mark.django_db
def test_collections_include_document_count(client, indexed_document):
    response = client.get(reverse("collection-list"))

    assert response.status_code == 200
    assert response.json()[0]["document_count"] == 1


@pytest.mark.django_db
def test_settings_endpoint(client):
    response = client.get(reverse("settings"))

    assert response.status_code == 200
    payload = response.json()
    assert payload["embedding_model"]
    assert payload["features"]["chat_query"] == "available"
    assert payload["features"]["document_upload"] == "available"
    assert payload["features"]["answer_generation"] in {"enabled", "disabled"}
