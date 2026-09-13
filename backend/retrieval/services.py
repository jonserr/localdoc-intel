from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Protocol

import requests
from django.conf import settings
from django.db.models import Q
from documents.models import DocumentChunk
from qdrant_client import QdrantClient
from qdrant_client.http import models as qm


class RetrievalError(RuntimeError):
    pass


BM25_K1 = 1.5
BM25_B = 0.75
RRF_RANK_CONSTANT = 60


class EmbeddingProvider(Protocol):
    def embed_query(self, text: str) -> list[float]: ...

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...


class VectorStore(Protocol):
    def upsert_chunks(
        self,
        chunks: list[DocumentChunk],
        vectors: list[list[float]],
    ) -> None: ...

    def search(
        self,
        query_vector: list[float],
        top_k: int,
        collection: str | None = None,
        metadata_filters: dict | None = None,
    ) -> list[VectorSearchResult]: ...


class Reranker(Protocol):
    def rerank(
        self, question: str, results: list[RetrievedChunk]
    ) -> list[RetrievedChunk]: ...


@dataclass(frozen=True)
class VectorSearchResult:
    chunk_id: int
    score: float
    payload: dict = field(default_factory=dict)


@dataclass(frozen=True)
class RetrievedChunk:
    chunk: DocumentChunk
    score: float
    source: str = "keyword"
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class IndexingResult:
    indexed: int
    skipped: int
    enabled: bool
    error: str = ""


class OllamaEmbeddingProvider:
    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        timeout_seconds: float | None = None,
    ):
        self.base_url = (base_url or settings.OLLAMA_BASE_URL).rstrip("/")
        self.model = model or settings.EMBEDDING_MODEL
        self.timeout_seconds = timeout_seconds or settings.OLLAMA_TIMEOUT_SECONDS

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def _embed(self, text: str) -> list[float]:
        response = requests.post(
            f"{self.base_url}/api/embeddings",
            json={"model": self.model, "prompt": text},
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        vector = payload.get("embedding")
        if not isinstance(vector, list) or not vector:
            raise RetrievalError("Ollama returned an empty embedding.")
        return [float(value) for value in vector]


class QdrantVectorStore:
    def __init__(
        self,
        client: QdrantClient | None = None,
        collection_name: str | None = None,
        vector_size: int | None = None,
    ):
        self.client = client or QdrantClient(url=settings.QDRANT_URL)
        self.collection_name = collection_name or settings.QDRANT_COLLECTION
        self.vector_size = vector_size or settings.QDRANT_VECTOR_SIZE

    def ensure_collection(self) -> None:
        collections = self.client.get_collections().collections
        existing = {collection.name for collection in collections}
        if self.collection_name in existing:
            return
        self.client.create_collection(
            collection_name=self.collection_name,
            vectors_config=qm.VectorParams(
                size=self.vector_size,
                distance=qm.Distance.COSINE,
            ),
        )

    def upsert_chunks(
        self,
        chunks: list[DocumentChunk],
        vectors: list[list[float]],
    ) -> None:
        if len(chunks) != len(vectors):
            raise RetrievalError("Chunk and vector counts must match.")
        self.ensure_collection()
        points = [
            qm.PointStruct(
                id=chunk.id,
                vector=vector,
                payload=payload_for_chunk(chunk),
            )
            for chunk, vector in zip(chunks, vectors, strict=True)
        ]
        if points:
            self.client.upsert(collection_name=self.collection_name, points=points)

    def search(
        self,
        query_vector: list[float],
        top_k: int,
        collection: str | None = None,
        metadata_filters: dict | None = None,
    ) -> list[VectorSearchResult]:
        query_filter = build_qdrant_filter(collection, metadata_filters)
        response = self.client.query_points(
            collection_name=self.collection_name,
            query=query_vector,
            query_filter=query_filter,
            limit=top_k,
            with_payload=True,
        )
        points = getattr(response, "points", response)
        return [
            VectorSearchResult(
                chunk_id=int(point.id),
                score=float(point.score),
                payload=point.payload or {},
            )
            for point in points
        ]


class KeywordReranker:
    def rerank(
        self, question: str, results: list[RetrievedChunk]
    ) -> list[RetrievedChunk]:
        question_terms = tokenize_terms(question)
        result_terms = {
            item.chunk.id: tokenize_terms(item.chunk.text) for item in results
        }
        scores = bm25_scores(question_terms, result_terms)
        return sorted(
            results,
            key=lambda item: (
                scores.get(item.chunk.id, 0.0),
                item.score,
            ),
            reverse=True,
        )


def payload_for_chunk(chunk: DocumentChunk) -> dict:
    document = chunk.document
    return {
        "chunk_id": chunk.id,
        "document_id": document.id,
        "document_title": document.title,
        "collection": document.collection.name,
        "file_type": document.file_type,
        "chunk_index": chunk.chunk_index,
        "page": chunk.page,
        "start_line": chunk.start_line,
        "end_line": chunk.end_line,
        "byte_start": chunk.byte_start,
        "byte_end": chunk.byte_end,
        "text_preview": chunk.text[:240],
    }


def build_qdrant_filter(
    collection: str | None = None,
    metadata_filters: dict | None = None,
) -> qm.Filter | None:
    conditions = []
    if collection:
        conditions.append(
            qm.FieldCondition(
                key="collection",
                match=qm.MatchValue(value=collection),
            )
        )

    for key, value in (metadata_filters or {}).items():
        if value in (None, ""):
            continue
        conditions.append(
            qm.FieldCondition(
                key=key,
                match=qm.MatchValue(value=value),
            )
        )

    if not conditions:
        return None
    return qm.Filter(must=conditions)


def index_document_chunks(
    document_id: int,
    embedding_provider: EmbeddingProvider | None = None,
    vector_store: VectorStore | None = None,
    enabled: bool | None = None,
) -> IndexingResult:
    should_index = settings.VECTOR_INDEXING_ENABLED if enabled is None else enabled
    chunks = list(
        DocumentChunk.objects.select_related("document", "document__collection")
        .filter(document_id=document_id)
        .order_by("chunk_index")
    )
    if not should_index:
        return IndexingResult(indexed=0, skipped=len(chunks), enabled=False)
    if not chunks:
        return IndexingResult(indexed=0, skipped=0, enabled=True)

    provider = embedding_provider or OllamaEmbeddingProvider()
    store = vector_store or QdrantVectorStore()

    try:
        vectors = provider.embed_documents([chunk.text for chunk in chunks])
        store.upsert_chunks(chunks, vectors)
    except Exception as exc:
        return IndexingResult(
            indexed=0,
            skipped=len(chunks),
            enabled=True,
            error=str(exc),
        )

    for chunk in chunks:
        chunk.embedding_id = f"{settings.QDRANT_COLLECTION}:{chunk.id}"
    DocumentChunk.objects.bulk_update(chunks, ["embedding_id"])
    return IndexingResult(indexed=len(chunks), skipped=0, enabled=True)


@dataclass(frozen=True)
class RetrievalOutcome:
    """Retrieved chunks plus the strategy that actually produced them.

    ``requested_mode`` is what the caller asked for. ``strategy`` is what ran:
    ``vector``, ``hybrid``, or ``bm25``. When the two differ, ``fallback_reason``
    says why, so evaluation runs never report BM25 results as vector results.
    """

    chunks: list[RetrievedChunk]
    requested_mode: str
    strategy: str
    fallback_reason: str = ""
    dense_result_count: int = 0
    keyword_result_count: int = 0


def retrieve_chunks(
    question: str,
    collection: str | None = None,
    top_k: int = 5,
    mode: str = "hybrid",
    rerank: bool = False,
    metadata_filters: dict | None = None,
    embedding_provider: EmbeddingProvider | None = None,
    vector_store: VectorStore | None = None,
    reranker: Reranker | None = None,
) -> list[RetrievedChunk]:
    """Return retrieved chunks only. See ``retrieve`` for the full outcome."""
    return retrieve(
        question=question,
        collection=collection,
        top_k=top_k,
        mode=mode,
        rerank=rerank,
        metadata_filters=metadata_filters,
        embedding_provider=embedding_provider,
        vector_store=vector_store,
        reranker=reranker,
    ).chunks


def retrieve(
    question: str,
    collection: str | None = None,
    top_k: int = 5,
    mode: str = "hybrid",
    rerank: bool = False,
    metadata_filters: dict | None = None,
    embedding_provider: EmbeddingProvider | None = None,
    vector_store: VectorStore | None = None,
    reranker: Reranker | None = None,
) -> RetrievalOutcome:
    if mode not in {"vector", "hybrid", "metadata-filtered"}:
        raise RetrievalError(f"Unsupported retrieval mode '{mode}'.")

    dense_results: list[RetrievedChunk] = []
    fallback_reason = ""
    use_dense = (
        settings.VECTOR_SEARCH_ENABLED
        or embedding_provider is not None
        or vector_store is not None
    )
    if use_dense:
        dense_results, dense_error = dense_retrieve_with_status(
            question=question,
            collection=collection,
            top_k=top_k,
            metadata_filters=metadata_filters,
            embedding_provider=embedding_provider,
            vector_store=vector_store,
        )
        if dense_error:
            fallback_reason = f"vector search failed: {dense_error}"
        elif not dense_results:
            fallback_reason = "vector search returned no results"
    else:
        fallback_reason = "vector search disabled (VECTOR_SEARCH_ENABLED=false)"

    keyword_results: list[RetrievedChunk] = []
    results = dense_results
    if mode == "hybrid" or not dense_results:
        keyword_results = keyword_retrieve(
            question=question,
            collection=collection,
            top_k=top_k,
            metadata_filters=metadata_filters,
        )
        results = merge_results(dense_results, keyword_results)

    if dense_results and keyword_results:
        strategy = "hybrid"
    elif dense_results:
        strategy = "vector"
    else:
        strategy = "bm25"
    if dense_results:
        fallback_reason = ""

    if rerank:
        results = (reranker or KeywordReranker()).rerank(question, results)

    return RetrievalOutcome(
        chunks=results[:top_k],
        requested_mode=mode,
        strategy=strategy,
        fallback_reason=fallback_reason,
        dense_result_count=len(dense_results),
        keyword_result_count=len(keyword_results),
    )


def dense_retrieve(
    question: str,
    collection: str | None,
    top_k: int,
    metadata_filters: dict | None = None,
    embedding_provider: EmbeddingProvider | None = None,
    vector_store: VectorStore | None = None,
) -> list[RetrievedChunk]:
    results, _ = dense_retrieve_with_status(
        question=question,
        collection=collection,
        top_k=top_k,
        metadata_filters=metadata_filters,
        embedding_provider=embedding_provider,
        vector_store=vector_store,
    )
    return results


def dense_retrieve_with_status(
    question: str,
    collection: str | None,
    top_k: int,
    metadata_filters: dict | None = None,
    embedding_provider: EmbeddingProvider | None = None,
    vector_store: VectorStore | None = None,
) -> tuple[list[RetrievedChunk], str]:
    """Run vector search; return (results, error). Errors never propagate.

    Hits below ``settings.VECTOR_MIN_SCORE`` are dropped. Unlike the lexical
    path, where a zero BM25 score means no query term matched, a low cosine
    score has no corpus-independent meaning, so the floor is configuration
    rather than a fixed rule.
    """
    provider = embedding_provider or OllamaEmbeddingProvider()
    store = vector_store or QdrantVectorStore()
    try:
        query_vector = provider.embed_query(question)
        vector_results = store.search(
            query_vector=query_vector,
            top_k=top_k,
            collection=collection,
            metadata_filters=metadata_filters,
        )
    except Exception as exc:
        return [], f"{type(exc).__name__}: {exc}"

    chunks_by_id = {
        chunk.id: chunk
        for chunk in DocumentChunk.objects.select_related(
            "document", "document__collection"
        ).filter(id__in=[result.chunk_id for result in vector_results])
    }
    minimum_score = settings.VECTOR_MIN_SCORE
    retrieved = []
    for result in vector_results:
        chunk = chunks_by_id.get(result.chunk_id)
        # A vector store returns the nearest neighbours whether or not they are
        # relevant. VECTOR_MIN_SCORE is the optional relevance floor; at the
        # default 0.0 every neighbour is kept.
        if chunk and result.score >= minimum_score:
            retrieved.append(
                RetrievedChunk(
                    chunk=chunk,
                    score=result.score,
                    source="vector",
                    metadata=result.payload,
                )
            )
    return retrieved, ""


# A query term that appears in almost every chunk carries no signal: matching
# it says nothing about relevance. Rather than ship a stopword list (which is
# language-specific and wrong for code or log corpora), terms are judged
# against the corpus in scope. The floor keeps this off for tiny corpora,
# where document frequency is meaningless.
UBIQUITOUS_TERM_RATIO = 0.9
MIN_CHUNKS_FOR_TERM_STATISTICS = 5


def informative_terms(
    terms: list[str],
    candidate_terms: dict[int, list[str]],
    corpus_size: int,
) -> list[str]:
    """Drop query terms that appear in nearly every chunk of the corpus."""
    if corpus_size < MIN_CHUNKS_FOR_TERM_STATISTICS:
        return terms
    document_frequency = Counter()
    for chunk_terms in candidate_terms.values():
        for term in set(chunk_terms):
            document_frequency[term] += 1
    kept = [
        term
        for term in terms
        if document_frequency[term] / corpus_size < UBIQUITOUS_TERM_RATIO
    ]
    return kept


def keyword_retrieve(
    question: str,
    collection: str | None,
    top_k: int,
    metadata_filters: dict | None = None,
) -> list[RetrievedChunk]:
    """BM25-rank every chunk that lexically matches an informative query term.

    Candidate selection is by relevance, not by insertion order: all chunks
    that contain at least one query term are loaded and scored, then the top
    ``top_k`` positive scores are returned.

    A question returns nothing when it has no usable tokens, when no chunk
    contains any of its terms, or when the only terms that match are ubiquitous
    in the corpus (see ``informative_terms``). Chunks that match only as a
    substring (``icontains``) but not as a whole token score zero and are
    excluded.

    Scale limitation: this loads and scores the full lexical candidate set in
    Python, so the cost grows with the size of that set. A common term over a
    large corpus makes the scoring pass expensive. A larger corpus needs an
    indexed lexical stage (for example Postgres full-text search) ahead of
    BM25, and its recall should be measured rather than assumed.
    """
    terms = tokenize_terms(question)
    if not terms:
        return []
    unique_terms = set(terms)
    queryset = DocumentChunk.objects.select_related("document", "document__collection")
    if collection:
        queryset = queryset.filter(document__collection__name__iexact=collection)
    queryset = apply_metadata_filters(queryset, metadata_filters)
    corpus_size = queryset.count()

    condition = Q()
    for term in unique_terms:
        condition |= Q(text__icontains=term)
    candidates = list(queryset.filter(condition).order_by("document_id", "chunk_index"))
    if not candidates:
        return []

    candidate_terms = {chunk.id: tokenize_terms(chunk.text) for chunk in candidates}
    scoring_terms = informative_terms(terms, candidate_terms, corpus_size)
    if not scoring_terms:
        return []

    scores = {
        chunk_id: score
        for chunk_id, score in bm25_scores(scoring_terms, candidate_terms).items()
        if score > 0
    }
    if not scores:
        return []
    # Relative lexical scores are useful within BM25 only. Hybrid fusion uses
    # ranks, never compares these values with raw dense cosine scores.
    max_score = max(scores.values())
    ranked = [
        RetrievedChunk(
            chunk=chunk,
            score=scores[chunk.id] / max_score,
            source="bm25",
            metadata={**payload_for_chunk(chunk), "keyword_ranker": "bm25"},
        )
        for chunk in candidates
        if chunk.id in scores
    ]
    # Stable order: score first, then document/chunk position for ties.
    ranked.sort(
        key=lambda item: (-item.score, item.chunk.document_id, item.chunk.chunk_index)
    )
    return ranked[:top_k]


def apply_metadata_filters(queryset, metadata_filters: dict | None):
    for key, value in (metadata_filters or {}).items():
        if value in (None, ""):
            continue
        if key == "file_type":
            queryset = queryset.filter(document__file_type__iexact=value)
        elif key == "document_id":
            queryset = queryset.filter(document_id=value)
        elif key == "page":
            queryset = queryset.filter(page=value)
    return queryset


def merge_results(
    primary: list[RetrievedChunk],
    secondary: list[RetrievedChunk],
) -> list[RetrievedChunk]:
    """Equal-weight reciprocal rank fusion of dense and BM25 rankings.

    Each distinct hit contributes 1 / (60 + rank) per retriever. Scores from
    the two providers are deliberately not compared. Equal fused scores keep
    dense-first encounter order, then lexical order; that tie-break is not a
    relevance guarantee. A single active list retains its original scores.
    """
    if not primary or not secondary:
        return list(primary or secondary)

    items: dict[int, RetrievedChunk] = {}
    scores: dict[int, float] = {}
    ranks: dict[int, dict] = {}
    metadata: dict[int, dict] = {}
    for label, results in (("dense", primary), ("bm25", secondary)):
        seen: set[int] = set()
        for rank, item in enumerate(results, start=1):
            chunk_id = item.chunk.id
            if chunk_id in seen:
                continue
            seen.add(chunk_id)
            items.setdefault(chunk_id, item)
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1 / (
                RRF_RANK_CONSTANT + rank
            )
            ranks.setdefault(chunk_id, {})[label] = rank
            metadata[chunk_id] = {**item.metadata, **metadata.get(chunk_id, {})}

    fused = [
        RetrievedChunk(
            chunk=item.chunk,
            score=scores[chunk_id],
            source="hybrid" if len(ranks[chunk_id]) == 2 else item.source,
            metadata={
                **metadata[chunk_id],
                "fusion": "rrf",
                "rrf_rank_constant": RRF_RANK_CONSTANT,
                "retriever_ranks": ranks[chunk_id],
            },
        )
        for chunk_id, item in items.items()
    ]
    return sorted(fused, key=lambda item: item.score, reverse=True)


def tokenize(text: str) -> set[str]:
    return set(tokenize_terms(text))


def tokenize_terms(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z0-9_]{2,}", text.lower())


def bm25_scores(
    query_terms: list[str],
    document_terms: dict[int, list[str]],
) -> dict[int, float]:
    if not query_terms or not document_terms:
        return {document_id: 0.0 for document_id in document_terms}

    query_counts = Counter(query_terms)
    term_counts = {
        document_id: Counter(terms) for document_id, terms in document_terms.items()
    }
    document_lengths = {
        document_id: max(sum(counts.values()), 1)
        for document_id, counts in term_counts.items()
    }
    average_length = sum(document_lengths.values()) / len(document_lengths)
    document_count = len(document_terms)
    document_frequencies = Counter()
    for counts in term_counts.values():
        for term in counts:
            document_frequencies[term] += 1

    scores = {}
    for document_id, counts in term_counts.items():
        score = 0.0
        length = document_lengths[document_id]
        for term, query_frequency in query_counts.items():
            term_frequency = counts.get(term, 0)
            if term_frequency == 0:
                continue
            document_frequency = document_frequencies[term]
            inverse_document_frequency = math.log(
                1
                + (document_count - document_frequency + 0.5)
                / (document_frequency + 0.5)
            )
            denominator = term_frequency + BM25_K1 * (
                1 - BM25_B + BM25_B * (length / average_length)
            )
            score += (
                inverse_document_frequency
                * ((term_frequency * (BM25_K1 + 1)) / denominator)
                * query_frequency
            )
        scores[document_id] = score
    return scores


def lexical_score(question_terms: set[str], text: str) -> float:
    if not question_terms:
        return 0.0
    text_terms = tokenize(text)
    overlap = len(question_terms & text_terms)
    if overlap == 0:
        return 0.0
    return overlap / math.sqrt(len(question_terms) * max(len(text_terms), 1))
