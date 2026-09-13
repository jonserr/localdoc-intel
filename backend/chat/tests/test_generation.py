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


class ScriptedProvider:
    model = "fake-model"

    def __init__(self, answer: str):
        self.answer = answer

    def generate(self, question: str, context: str) -> str:
        return self.answer


@pytest.mark.django_db
def test_out_of_range_citation_is_rejected_and_falls_back(retrieved_chunks):
    result = generate_answer(
        "What is configured?",
        retrieved_chunks[:1],
        provider=ScriptedProvider("Unsupported claim [99]."),
        enabled=True,
    )

    assert result.mode == "extractive"
    assert result.citation_status == "invalid_references"
    assert result.invalid_citations == [99]
    assert result.cited_sources == [99]
    assert "[99]" in result.error
    assert "Unsupported claim" not in result.answer


@pytest.mark.django_db
def test_mixed_valid_and_invalid_citations_are_rejected(retrieved_chunks):
    result = generate_answer(
        "What is validated?",
        retrieved_chunks,
        provider=ScriptedProvider("Migrations [1], caches [2], and dragons [3]."),
        enabled=True,
    )

    assert result.mode == "extractive"
    assert result.citation_status == "invalid_references"
    assert result.cited_sources == [1, 2, 3]
    assert result.invalid_citations == [3]


@pytest.mark.django_db
def test_zero_is_not_a_valid_source_number(retrieved_chunks):
    result = generate_answer(
        "What is validated?",
        retrieved_chunks,
        provider=ScriptedProvider("See [0]."),
        enabled=True,
    )

    assert result.citation_status == "invalid_references"
    assert result.invalid_citations == [0]


@pytest.mark.django_db
def test_answer_without_citations_is_kept_but_flagged(retrieved_chunks):
    result = generate_answer(
        "What is validated?",
        retrieved_chunks,
        provider=ScriptedProvider("The sources do not say."),
        enabled=True,
    )

    assert result.mode == "generated"
    assert result.citation_status == "missing"
    assert result.cited_sources == []
    assert result.answer == "The sources do not say."


@pytest.mark.django_db
def test_valid_citations_are_reported(retrieved_chunks):
    result = generate_answer(
        "What is validated?",
        retrieved_chunks,
        provider=ScriptedProvider("Migrations [1] and logs [2] [1]."),
        enabled=True,
    )

    assert result.mode == "generated"
    assert result.citation_status == "valid"
    assert result.cited_sources == [1, 2]
    assert result.invalid_citations == []


@pytest.mark.django_db
def test_valid_marker_does_not_prove_support(retrieved_chunks):
    """Marker validation is structural. A wrong claim with a real number passes."""
    result = generate_answer(
        "What is validated?",
        retrieved_chunks,
        provider=ScriptedProvider("Deployment requires a blood sacrifice [1]."),
        enabled=True,
    )

    assert result.citation_status == "valid"
    assert "blood sacrifice" in result.answer


def test_validate_citations_pure_function():
    from chat.generation import validate_citations

    assert validate_citations("no markers", 3).status == "missing"
    assert validate_citations("[2] then [2] and [1]", 2).cited == [2, 1]
    assert validate_citations("[3]", 2).invalid == [3]
    assert validate_citations("", 0).status == "missing"
