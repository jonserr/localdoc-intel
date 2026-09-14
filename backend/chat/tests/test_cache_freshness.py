"""Same-day uploads must be considered before reusing generated answers."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from documents.models import Collection, Document, DocumentChunk

from chat.models import CachedArtifact


@pytest.mark.django_db
@pytest.mark.parametrize("relevant_uploads", [True, False])
def test_same_day_uploads_invalidate_answer_before_ttl(
    client, settings, mocker, tmp_path, relevant_uploads
):
    settings.MEDIA_ROOT = tmp_path
    settings.ANSWER_GENERATION_ENABLED = True
    mocker.patch("chat.views.inventory_target", return_value=None)
    morning = datetime(2026, 9, 13, 8, 25, tzinfo=ZoneInfo("America/New_York"))
    now = mocker.patch("chat.cache.timezone.now", return_value=morning)
    collection = Collection.objects.create(name="HR")
    documents = Document.objects.bulk_create(
        [
            Document(
                collection=collection,
                title=f"HR guide {index}",
                original_filename=f"hr-{index}.txt",
                file_type="txt",
                sha256=f"{index:064x}",
                status=Document.Status.INDEXED,
                chunk_count=1,
            )
            for index in range(1000)
        ]
    )
    DocumentChunk.objects.bulk_create(
        [
            DocumentChunk(
                document=document,
                chunk_index=0,
                text=(
                    "Security onboarding starts with orientation."
                    if index == 0
                    else f"Payroll benefit reference {index}."
                ),
            )
            for index, document in enumerate(documents)
        ]
    )
    provider = mocker.Mock(model="test-model")
    provider.generate.side_effect = lambda question, context: (
        "Use the Nimbus access checklist [1]."
        if "Nimbus" in context
        else "Start with orientation [1]."
    )
    mocker.patch("chat.generation.OllamaGenerationProvider", return_value=provider)
    # Exercise real retrieval, ingestion and caching; only Ollama is replaced.
    request = {
        "question": "What are the guides for onboarding security team member?",
        "collection": "hr",
        "retrieval_mode": "hybrid",
    }

    def ask():
        response = client.post(
            reverse("chat-query"), request, content_type="application/json"
        )
        assert response.status_code == 200
        return response.json()

    first = ask()
    assert first["metadata"]["answer_cached"] is False
    assert ask()["metadata"]["answer_cached"] is True
    assert provider.generate.call_count == 1
    original_cache = CachedArtifact.objects.get(kind="generation")

    now.return_value = morning.replace(hour=12, minute=0)
    text = (
        "Security team member onboarding guides: Nimbus access checklist"
        if relevant_uploads
        else "Payroll benefit reference supplement"
    )
    uploaded = client.post(
        reverse("document-upload"),
        {
            "collection": "HR",
            "files": [
                SimpleUploadedFile(f"new-{index}.txt", f"{text} {index}.".encode())
                for index in range(30)
            ],
        },
    )
    assert uploaded.status_code == 201
    assert uploaded.json()["errors"] == []
    added_ids = {row["document"]["id"] for row in uploaded.json()["documents"]}
    assert len(added_ids) == 30

    now.return_value = morning.replace(hour=13, minute=5)
    assert original_cache.expires_at > now.return_value
    afternoon = ask()
    assert afternoon["metadata"]["answer_cached"] is False
    assert afternoon["metadata"]["collection_document_count"] == 1030
    assert afternoon["metadata"]["collection_chunk_count"] == 1030
    assert provider.generate.call_count == 2
    if relevant_uploads:
        assert "Nimbus" in provider.generate.call_args.args[1]
        assert "Nimbus" in afternoon["answer"]
        assert afternoon["answer"] != first["answer"]
        assert added_ids & {row["document_id"] for row in afternoon["citations"]}
    else:
        # Even when the selected evidence is unchanged, changed scope sizes
        # invalidate the answer. Regeneration may legitimately say the same thing.
        assert afternoon["citations"] == first["citations"]
        assert afternoon["answer"] == first["answer"]
    assert ask()["metadata"]["answer_cached"] is True
    assert provider.generate.call_count == 2
