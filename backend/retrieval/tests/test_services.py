import pytest
from documents.models import Collection, Document, DocumentChunk

from retrieval.services import (
    RetrievedChunk,
    VectorSearchResult,
    build_qdrant_filter,
    index_document_chunks,
    retrieve_chunks,
)


class FakeEmbeddingProvider:
    def __init__(self):
        self.queries = []
        self.documents = []

    def embed_query(self, text: str) -> list[float]:
        self.queries.append(text)
        return [0.1, 0.2, 0.3]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.documents.extend(texts)
        return [[0.1, 0.2, 0.3] for _ in texts]


class FakeVectorStore:
    def __init__(self, results=None):
        self.upserts = []
        self.searches = []
        self.results = results or []

    def upsert_chunks(self, chunks, vectors) -> None:
        self.upserts.append((chunks, vectors))

    def search(self, query_vector, top_k, collection=None, metadata_filters=None):
        self.searches.append(
            {
                "query_vector": query_vector,
                "top_k": top_k,
                "collection": collection,
                "metadata_filters": metadata_filters,
            }
        )
        return self.results


class ReverseReranker:
    def rerank(self, question: str, results: list[RetrievedChunk]):
        return list(reversed(results))


@pytest.fixture
def chunks():
    platform = Collection.objects.create(name="Platform")
    research = Collection.objects.create(name="Research")
    platform_doc = Document.objects.create(
        collection=platform,
        title="Deployment Guide",
        original_filename="deployment.md",
        file_type="md",
        sha256="c" * 64,
        status=Document.Status.INDEXED,
        chunk_count=2,
        byte_size=512,
    )
    research_doc = Document.objects.create(
        collection=research,
        title="Experiment Notes",
        original_filename="notes.txt",
        file_type="txt",
        sha256="d" * 64,
        status=Document.Status.INDEXED,
        chunk_count=1,
        byte_size=128,
    )
    return {
        "deploy": DocumentChunk.objects.create(
            document=platform_doc,
            chunk_index=0,
            text="Validate migrations before deployment.",
            start_line=1,
            end_line=3,
        ),
        "cache": DocumentChunk.objects.create(
            document=platform_doc,
            chunk_index=1,
            text="Check cache connectivity and Redis health.",
            start_line=4,
            end_line=6,
        ),
        "research": DocumentChunk.objects.create(
            document=research_doc,
            chunk_index=0,
            text="Summarize experiment notes and observations.",
            start_line=1,
            end_line=2,
        ),
    }


@pytest.mark.django_db
def test_index_document_chunks_upserts_vectors_and_marks_embedding_ids(chunks):
    provider = FakeEmbeddingProvider()
    store = FakeVectorStore()
    document_id = chunks["deploy"].document_id

    result = index_document_chunks(
        document_id,
        embedding_provider=provider,
        vector_store=store,
        enabled=True,
    )

    assert result.indexed == 2
    assert result.skipped == 0
    assert provider.documents == [
        "Validate migrations before deployment.",
        "Check cache connectivity and Redis health.",
    ]
    upserted_chunks, vectors = store.upserts[0]
    assert [chunk.id for chunk in upserted_chunks] == [
        chunks["deploy"].id,
        chunks["cache"].id,
    ]
    assert vectors == [[0.1, 0.2, 0.3], [0.1, 0.2, 0.3]]
    chunks["deploy"].refresh_from_db()
    assert chunks["deploy"].embedding_id.endswith(f":{chunks['deploy'].id}")


@pytest.mark.django_db
def test_index_document_chunks_can_be_disabled(chunks):
    result = index_document_chunks(chunks["deploy"].document_id, enabled=False)

    assert result.enabled is False
    assert result.indexed == 0
    assert result.skipped == 2


@pytest.mark.django_db
def test_dense_retrieval_uses_qdrant_collection_and_metadata_filters(chunks):
    provider = FakeEmbeddingProvider()
    store = FakeVectorStore(
        results=[VectorSearchResult(chunk_id=chunks["deploy"].id, score=0.91)]
    )

    results = retrieve_chunks(
        question="deployment validation",
        collection="Platform",
        top_k=3,
        mode="vector",
        metadata_filters={"file_type": "md"},
        embedding_provider=provider,
        vector_store=store,
    )

    assert provider.queries == ["deployment validation"]
    assert store.searches[0]["collection"] == "Platform"
    assert store.searches[0]["metadata_filters"] == {"file_type": "md"}
    assert results[0].chunk == chunks["deploy"]
    assert results[0].score == 0.91
    assert results[0].source == "vector"


@pytest.mark.django_db
def test_hybrid_retrieval_merges_vector_and_keyword_results(chunks):
    provider = FakeEmbeddingProvider()
    store = FakeVectorStore(
        results=[VectorSearchResult(chunk_id=chunks["cache"].id, score=0.2)]
    )

    results = retrieve_chunks(
        question="validate deployment migrations",
        collection="Platform",
        top_k=3,
        mode="hybrid",
        embedding_provider=provider,
        vector_store=store,
    )

    ids = [item.chunk.id for item in results]
    assert chunks["deploy"].id in ids
    assert chunks["cache"].id in ids
    assert all(item.chunk.document.collection.name == "Platform" for item in results)


@pytest.mark.django_db
def test_metadata_filtered_keyword_fallback_scopes_file_type(chunks):
    results = retrieve_chunks(
        question="notes observations",
        top_k=5,
        mode="metadata-filtered",
        metadata_filters={"file_type": "txt"},
    )

    assert [item.chunk.id for item in results] == [chunks["research"].id]


@pytest.mark.django_db
def test_keyword_retrieval_uses_bm25_term_frequency():
    collection = Collection.objects.create(name="Search")
    document = Document.objects.create(
        collection=collection,
        title="Cache Notes",
        original_filename="cache.md",
        file_type="md",
        sha256="e" * 64,
        status=Document.Status.INDEXED,
        chunk_count=2,
        byte_size=256,
    )
    concise = DocumentChunk.objects.create(
        document=document,
        chunk_index=0,
        text="cache",
    )
    detailed = DocumentChunk.objects.create(
        document=document,
        chunk_index=1,
        text="cache cache cache cache eviction ttl Redis cache",
    )

    results = retrieve_chunks(
        question="cache",
        collection="Search",
        top_k=2,
        mode="metadata-filtered",
    )

    assert [item.chunk.id for item in results] == [detailed.id, concise.id]
    assert results[0].source == "bm25"
    assert results[0].score > results[1].score


@pytest.mark.django_db
def test_reranker_interface_can_reorder_results(chunks):
    results = retrieve_chunks(
        question="deployment cache",
        collection="Platform",
        top_k=2,
        mode="hybrid",
        rerank=True,
        reranker=ReverseReranker(),
    )

    assert [item.chunk.id for item in results] == [
        chunks["cache"].id,
        chunks["deploy"].id,
    ]


def test_build_qdrant_filter_includes_collection_and_metadata():
    qdrant_filter = build_qdrant_filter(
        collection="Platform",
        metadata_filters={"file_type": "md", "page": 2},
    )

    assert qdrant_filter is not None
    assert len(qdrant_filter.must) == 3
    assert [condition.key for condition in qdrant_filter.must] == [
        "collection",
        "file_type",
        "page",
    ]
