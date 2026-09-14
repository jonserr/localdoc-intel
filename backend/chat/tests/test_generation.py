import pytest
import requests
from documents.models import Collection, Document, DocumentChunk
from retrieval.services import RetrievedChunk

from chat.generation import (
    SYSTEM_INSTRUCTIONS,
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


@pytest.mark.django_db
def test_context_reports_actual_source_count_not_document_count(retrieved_chunks):
    context = build_context(retrieved_chunks)

    assert "Retrieved sources supplied: 2 chunks." in context
    assert "partial sample, not a complete collection review" in context
    assert "Multiple chunks may come from the same document" in context
    assert "Documents in the searched collection(s):" not in context
    assert "Chunks in the searched collection(s):" not in context


def test_empty_context_reports_zero_sources_and_known_empty_scope():
    context = build_context([], collection_document_count=0, collection_chunk_count=0)

    assert "Retrieved sources supplied: 0 chunks." in context
    assert "Documents in the searched collection(s): 0." in context
    assert "Chunks in the searched collection(s): 0." in context


@pytest.mark.django_db
def test_generation_supplies_coverage_to_model(retrieved_chunks, mocker):
    provider = mocker.Mock(model="fake-model")
    provider.generate.return_value = "Validate migrations [1]."

    generate_answer(
        "What is validated?",
        retrieved_chunks,
        provider=provider,
        enabled=True,
        collection_document_count=1158,
        collection_chunk_count=2565,
    )

    question, context = provider.generate.call_args.args
    assert question == "What is validated?"
    assert "Retrieved sources supplied: 2 chunks." in context
    assert "Documents in the searched collection(s): 1158." in context
    assert "Chunks in the searched collection(s): 2565." in context


def test_system_instructions_forbid_whole_collection_claims(mocker):
    response = mocker.Mock()
    response.json.return_value = {
        "message": {"content": "The sources cannot settle it."}
    }
    post = mocker.patch("chat.generation.requests.post", return_value=response)

    OllamaGenerationProvider().generate("What businesses are there?", "Sources:")

    system = post.call_args.kwargs["json"]["messages"][0]
    assert system == {"role": "system", "content": SYSTEM_INSTRUCTIONS}
    assert "partial subset retrieved from a larger collection" in system["content"]
    assert (
        "Do not make whole-collection claims: counts, totals, inventories"
        in system["content"]
    )
    assert "all, only, or none" in system["content"]
    assert "When a question needs the full collection" in system["content"]
    assert "retrieved sources cannot settle it" in system["content"]
    assert "examples explicitly scoped to the retrieved sources" in system["content"]
    assert "For a lookup about a specific document" in system["content"]


def test_inventory_instructions_reject_exhaustive_sample_wording():
    assert "full-inventory request, even without the word 'all'" in SYSTEM_INSTRUCTIONS
    assert (
        "first sentence must say that these retrieved passages cannot establish "
        "the full list in the collection" in SYSTEM_INSTRUCTIONS
    )
    assert "Examples in the retrieved passages include" in SYSTEM_INSTRUCTIONS
    assert (
        "Never describe such an example list as 'only two', 'the only', or 'no other'"
        in SYSTEM_INSTRUCTIONS
    )
    assert "even with the qualifier 'in the provided sources'" in SYSTEM_INSTRUCTIONS
    assert "absence from an excerpt is not evidence of absence" in SYSTEM_INSTRUCTIONS
    assert "For both inventory and entity-count questions" in SYSTEM_INSTRUCTIONS
    assert "always call any names non-exhaustive examples" in SYSTEM_INSTRUCTIONS
    assert (
        "Do not characterize the documents as containing 'only a few' entities"
        in SYSTEM_INSTRUCTIONS
    )


@pytest.mark.django_db
def test_answer_cache_reuses_only_unchanged_evidence_and_question(
    retrieved_chunks, mocker
):
    provider = mocker.Mock(model="fake-model")
    provider.generate.return_value = "Validate migrations [1]."
    first = generate_answer(
        "What is validated?",
        retrieved_chunks,
        provider=provider,
        enabled=True,
        use_cache=True,
    )
    second = generate_answer(
        "What is validated?",
        retrieved_chunks,
        provider=provider,
        enabled=True,
        use_cache=True,
    )
    assert not first.cached and second.cached
    assert first.answer == second.answer
    assert provider.generate.call_count == 1
    retrieved_chunks[0].chunk.text = "Changed instructions."
    changed = generate_answer(
        "What is validated?",
        retrieved_chunks,
        provider=provider,
        enabled=True,
        use_cache=True,
    )
    assert not changed.cached
    different = generate_answer(
        "What changed?",
        retrieved_chunks,
        provider=provider,
        enabled=True,
        use_cache=True,
    )
    assert not different.cached
    assert provider.generate.call_count == 3


@pytest.mark.django_db
def test_failed_generation_is_not_cached(retrieved_chunks, mocker):
    provider = mocker.Mock(model="fake-model")
    provider.generate.side_effect = requests.ConnectionError("offline")
    for _ in range(2):
        result = generate_answer(
            "Question?",
            retrieved_chunks,
            provider=provider,
            enabled=True,
            use_cache=True,
        )
        assert result.mode == "extractive" and not result.cached
    assert provider.generate.call_count == 2
