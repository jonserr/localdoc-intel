"""Regression tests for lexical candidate selection and no-result behavior."""

import pytest
from documents.models import Collection, Document, DocumentChunk

from retrieval.services import VectorSearchResult, retrieve, retrieve_chunks


class FakeEmbeddingProvider:
    def embed_query(self, text: str) -> list[float]:
        return [0.1, 0.2, 0.3]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.2, 0.3] for _ in texts]


class FailingEmbeddingProvider:
    def embed_query(self, text: str) -> list[float]:
        raise ConnectionError("synthetic Ollama outage")

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise ConnectionError("synthetic Ollama outage")


class FakeVectorStore:
    def __init__(self, results=None):
        self.results = results or []

    def upsert_chunks(self, chunks, vectors) -> None:
        pass

    def search(self, query_vector, top_k, collection=None, metadata_filters=None):
        return self.results


def make_document(title: str = "notes.txt", digest: str = "a") -> Document:
    collection, _ = Collection.objects.get_or_create(name="Synthetic corpus")
    return Document.objects.create(
        collection=collection,
        title=title,
        original_filename=title,
        file_type="txt",
        sha256=digest * 64,
    )


@pytest.mark.django_db
def test_unrelated_question_returns_no_passages():
    document = make_document()
    DocumentChunk.objects.create(
        document=document, chunk_index=0, text="Redis cache configuration"
    )

    outcome = retrieve("platypus astronomy", mode="hybrid")

    assert outcome.chunks == []
    assert outcome.strategy == "bm25"
    assert outcome.keyword_result_count == 0


@pytest.mark.django_db
def test_question_without_usable_tokens_returns_nothing():
    document = make_document()
    DocumentChunk.objects.create(document=document, chunk_index=0, text="a b c")

    assert retrieve_chunks("?? !! -", mode="hybrid") == []
    assert retrieve_chunks("a", mode="hybrid") == []


@pytest.mark.django_db
def test_substring_match_without_token_match_scores_zero_and_is_excluded():
    document = make_document()
    DocumentChunk.objects.create(
        document=document, chunk_index=0, text="Redis cache configuration"
    )

    # "cach" passes text__icontains but is not a whole token in the chunk.
    assert retrieve_chunks("cach", mode="hybrid") == []
    # The whole token still matches.
    assert len(retrieve_chunks("cache", mode="hybrid")) == 1


@pytest.mark.django_db
@pytest.mark.parametrize("top_k", [1, 3, 10])
def test_best_match_after_candidate_limit_still_wins(top_k):
    document = make_document()
    DocumentChunk.objects.bulk_create(
        [
            DocumentChunk(
                document=document,
                chunk_index=index,
                text="the routine deployment notes",
            )
            for index in range(60)
        ]
    )
    target = DocumentChunk.objects.create(
        document=document, chunk_index=60, text="the quasar quasar quasar"
    )

    results = retrieve_chunks("the quasar", mode="hybrid", top_k=top_k)

    # "the" is ubiquitous here, so only the chunk matching "quasar" comes back.
    assert [item.chunk.id for item in results] == [target.id]
    assert results[0].score == 1.0


@pytest.mark.django_db
@pytest.mark.parametrize("top_k", [1, 3, 10])
def test_best_match_before_generic_chunks_wins_in_reversed_order(top_k):
    document = make_document()
    target = DocumentChunk.objects.create(
        document=document, chunk_index=0, text="the quasar quasar quasar"
    )
    DocumentChunk.objects.bulk_create(
        [
            DocumentChunk(
                document=document,
                chunk_index=index,
                text="the routine deployment notes",
            )
            for index in range(1, 61)
        ]
    )

    results = retrieve_chunks("the quasar", mode="hybrid", top_k=top_k)

    assert [item.chunk.id for item in results] == [target.id]


@pytest.mark.django_db
def test_best_match_across_documents_is_not_hidden_by_document_order():
    older = make_document("older.txt", "b")
    newer = make_document("newer.txt", "c")
    DocumentChunk.objects.bulk_create(
        [
            DocumentChunk(document=older, chunk_index=index, text="quasar survey log")
            for index in range(60)
        ]
    )
    target = DocumentChunk.objects.create(
        document=newer, chunk_index=0, text="quasar quasar quasar quasar redshift"
    )

    results = retrieve_chunks("quasar redshift", mode="hybrid", top_k=2)

    assert results[0].chunk.id == target.id


@pytest.mark.django_db
def test_requested_vector_mode_records_bm25_fallback_when_search_disabled():
    document = make_document()
    chunk = DocumentChunk.objects.create(
        document=document, chunk_index=0, text="Redis cache configuration"
    )

    outcome = retrieve("redis cache", mode="vector")

    assert outcome.requested_mode == "vector"
    assert outcome.strategy == "bm25"
    assert "disabled" in outcome.fallback_reason
    assert [item.chunk.id for item in outcome.chunks] == [chunk.id]


@pytest.mark.django_db
def test_vector_search_failure_is_recorded_as_fallback_reason():
    document = make_document()
    DocumentChunk.objects.create(
        document=document, chunk_index=0, text="Redis cache configuration"
    )

    outcome = retrieve(
        "redis cache",
        mode="vector",
        embedding_provider=FailingEmbeddingProvider(),
        vector_store=FakeVectorStore(),
    )

    assert outcome.strategy == "bm25"
    assert outcome.fallback_reason.startswith("vector search failed: ConnectionError")


@pytest.mark.django_db
def test_vector_results_report_vector_strategy_without_fallback():
    document = make_document()
    chunk = DocumentChunk.objects.create(
        document=document, chunk_index=0, text="Redis cache configuration"
    )

    outcome = retrieve(
        "unrelated wording",
        mode="vector",
        embedding_provider=FakeEmbeddingProvider(),
        vector_store=FakeVectorStore([VectorSearchResult(chunk.id, 0.8)]),
    )

    assert outcome.strategy == "vector"
    assert outcome.fallback_reason == ""
    assert outcome.dense_result_count == 1
    assert outcome.chunks[0].source == "vector"


class ScoredVectorStore:
    def __init__(self, scored):
        self.scored = scored

    def upsert_chunks(self, chunks, vectors) -> None:
        pass

    def search(self, query_vector, top_k, collection=None, metadata_filters=None):
        return [
            VectorSearchResult(chunk_id=chunk_id, score=score)
            for chunk_id, score in self.scored
        ]


@pytest.mark.django_db
def test_vector_min_score_floor_drops_weak_hits(settings):
    document = make_document()
    strong = DocumentChunk.objects.create(
        document=document, chunk_index=0, text="Redis cache configuration"
    )
    weak = DocumentChunk.objects.create(
        document=document, chunk_index=1, text="Unrelated content"
    )
    settings.VECTOR_MIN_SCORE = 0.4

    outcome = retrieve(
        "zzz qqq",
        mode="vector",
        embedding_provider=FakeEmbeddingProvider(),
        vector_store=ScoredVectorStore([(strong.id, 0.62), (weak.id, 0.31)]),
    )

    assert [item.chunk.id for item in outcome.chunks] == [strong.id]


@pytest.mark.django_db
def test_default_vector_floor_keeps_every_hit(settings):
    document = make_document()
    chunk = DocumentChunk.objects.create(
        document=document, chunk_index=0, text="Redis cache configuration"
    )
    assert settings.VECTOR_MIN_SCORE == 0.0

    outcome = retrieve(
        "zzz qqq",
        mode="vector",
        embedding_provider=FakeEmbeddingProvider(),
        vector_store=ScoredVectorStore([(chunk.id, 0.05)]),
    )

    assert len(outcome.chunks) == 1


@pytest.mark.django_db
def test_vector_floor_that_rejects_everything_yields_no_results(settings):
    document = make_document()
    chunk = DocumentChunk.objects.create(
        document=document, chunk_index=0, text="Redis cache configuration"
    )
    settings.VECTOR_MIN_SCORE = 0.9

    outcome = retrieve(
        "platypus astronomy",
        mode="vector",
        embedding_provider=FakeEmbeddingProvider(),
        vector_store=ScoredVectorStore([(chunk.id, 0.30)]),
    )

    assert outcome.chunks == []
    assert outcome.strategy == "bm25"
    assert outcome.fallback_reason == "vector search returned no results"


@pytest.mark.django_db
def test_ubiquitous_terms_alone_do_not_retrieve_anything():
    """ "the" matching every chunk is not evidence that a question is answerable."""
    document = make_document()
    DocumentChunk.objects.bulk_create(
        [
            DocumentChunk(
                document=document,
                chunk_index=index,
                text=f"the shared preamble line {index}",
            )
            for index in range(8)
        ]
    )
    DocumentChunk.objects.create(
        document=document, chunk_index=8, text="the runbook covers rollback"
    )

    assert retrieve_chunks("the orbital period of Enceladus", mode="hybrid") == []
    # An informative term in the same question still retrieves.
    assert len(retrieve_chunks("the runbook", mode="hybrid")) == 1


@pytest.mark.django_db
def test_ubiquitous_term_filtering_is_disabled_for_tiny_corpora():
    """Document frequency is meaningless below a handful of chunks."""
    document = make_document()
    DocumentChunk.objects.create(
        document=document, chunk_index=0, text="the deployment runbook"
    )

    # With one chunk, "the" is still allowed to match rather than being
    # declared ubiquitous from a sample of one.
    assert len(retrieve_chunks("the", mode="hybrid")) == 1


@pytest.mark.django_db
def test_informative_term_survives_alongside_ubiquitous_ones():
    document = make_document()
    DocumentChunk.objects.bulk_create(
        [
            DocumentChunk(
                document=document, chunk_index=index, text="the routine notes"
            )
            for index in range(10)
        ]
    )
    target = DocumentChunk.objects.create(
        document=document, chunk_index=10, text="the quasar redshift survey"
    )

    results = retrieve_chunks("the quasar", mode="hybrid", top_k=3)

    assert results[0].chunk.id == target.id
    assert len(results) == 1
