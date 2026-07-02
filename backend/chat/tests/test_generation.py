import pytest
import requests
from documents.models import Collection, Document, DocumentChunk
from retrieval.services import RetrievedChunk

from chat.generation import (
    OllamaGenerationProvider,
    build_context,
    generate_answer,
)


@pytest.fixture
def retrieved_chunks():
    collection = Collection.objects.create(name="Platform")
    document = Document.objects.create(
        collection=collection,
        title="deployment_guide.md",
        original_filename="deployment_guide.md",
        file_type="md",
        sha256="c" * 64,
        status=Document.Status.INDEXED,
        chunk_count=2,
        byte_size=256,
    )
    first = DocumentChunk.objects.create(
        document=document,
        chunk_index=0,
        text="Before deployment, validate migrations and cache connectivity.",
        start_line=1,
        end_line=3,
    )
    second = DocumentChunk.objects.create(
        document=document,
        chunk_index=1,
        text="If validation fails, halt promotion and attach logs.",
        page=2,
    )
    return [
        RetrievedChunk(chunk=first, score=0.9, source="keyword"),
        RetrievedChunk(chunk=second, score=0.7, source="keyword"),
    ]


class FakeProvider:
    model = "fake-model"

    def generate(self, question: str, context: str) -> str:
        return f"Validated items are listed [1]. Context length: {len(context)}"


class FailingProvider:
    model = "fake-model"

    def generate(self, question: str, context: str) -> str:
        raise requests.ConnectionError("Ollama is not running")


def test_generate_answer_without_results_returns_guidance():
    result = generate_answer("Anything?", [])

    assert result.mode == "no_results"
    assert "No relevant passages" in result.answer


@pytest.mark.django_db
def test_generate_answer_disabled_uses_extractive_fallback(retrieved_chunks):
    result = generate_answer("What is validated?", retrieved_chunks, enabled=False)

    assert result.mode == "extractive"
    assert "[1] deployment_guide.md" in result.answer
    assert "migrations" in result.answer


@pytest.mark.django_db
def test_generate_answer_uses_provider_when_enabled(retrieved_chunks):
    result = generate_answer(
        "What is validated?",
        retrieved_chunks,
        provider=FakeProvider(),
        enabled=True,
    )

    assert result.mode == "generated"
    assert result.model == "fake-model"
    assert "[1]" in result.answer
    assert result.error == ""


@pytest.mark.django_db
def test_generate_answer_falls_back_when_provider_fails(retrieved_chunks):
    result = generate_answer(
        "What is validated?",
        retrieved_chunks,
        provider=FailingProvider(),
        enabled=True,
    )

    assert result.mode == "extractive"
    assert result.error != ""
    assert "deployment_guide.md" in result.answer


@pytest.mark.django_db
def test_build_context_numbers_sources_with_locations(retrieved_chunks):
    context = build_context(retrieved_chunks)

    assert "[1] deployment_guide.md (lines 1-3)" in context
    assert "[2] deployment_guide.md (page 2)" in context
    assert context.startswith("Sources:")


@pytest.mark.django_db
def test_ollama_provider_parses_chat_response(retrieved_chunks, mocker):
    response = mocker.Mock()
    response.json.return_value = {"message": {"content": "Answer [1]."}}
    response.raise_for_status.return_value = None
    post = mocker.patch("chat.generation.requests.post", return_value=response)

    provider = OllamaGenerationProvider(
        base_url="http://ollama.test", model="test-model", timeout_seconds=5
    )
    answer = provider.generate("Question?", "Sources: [1] doc")

    assert answer == "Answer [1]."
    payload = post.call_args.kwargs["json"]
    assert payload["model"] == "test-model"
    assert payload["stream"] is False
    assert payload["options"]["num_predict"] > 0
    assert payload["keep_alive"]
