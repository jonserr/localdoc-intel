"""Rank fusion does not compare provider score scales."""

from dataclasses import replace

import pytest
from documents.models import Collection, Document, DocumentChunk

from retrieval.services import (
    RetrievedChunk,
    VectorSearchResult,
    merge_results,
    retrieve,
)


def hit(pk, score, source):
    return RetrievedChunk(chunk=DocumentChunk(id=pk), score=score, source=source)


def test_agreement_outranks_single_provider_and_retains_provenance():
    dense = [hit(1, 0.4, "vector"), hit(2, 0.3, "vector")]
    lexical = [hit(3, 1.0, "bm25"), hit(2, 0.7, "bm25")]
    results = merge_results(dense, lexical)
    assert [x.chunk.id for x in results] == [2, 1, 3]
    assert results[0].score == pytest.approx(2 / 62)
    assert results[0].source == "hybrid"
    assert results[0].metadata["retriever_ranks"] == {"dense": 2, "bm25": 2}
    assert results[1].source == "vector"
    assert results[2].source == "bm25"
    assert all(x.metadata["fusion"] == "rrf" for x in results)


def test_fusion_is_invariant_to_score_scale_and_ignores_duplicate_votes():
    dense = [hit(1, 0.3, "vector"), hit(2, 0.2, "vector")]
    lexical = [hit(3, 1.0, "bm25"), hit(2, 0.5, "bm25")]
    baseline = merge_results(dense, lexical)
    changed = merge_results(
        [replace(x, score=x.score / 100) for x in dense],
        [replace(x, score=x.score * 100) for x in lexical],
    )
    assert [(x.chunk.id, x.score) for x in baseline] == [
        (x.chunk.id, x.score) for x in changed
    ]
    duplicated = merge_results(dense + [dense[0]], lexical)
    assert [(x.chunk.id, x.score) for x in baseline] == [
        (x.chunk.id, x.score) for x in duplicated
    ]


@pytest.mark.parametrize("dense", [True, False])
def test_single_provider_retains_scores_and_order(dense):
    hits = [
        hit(1, 0.5, "vector" if dense else "bm25"),
        hit(2, 0.2, "vector" if dense else "bm25"),
    ]
    assert merge_results(hits if dense else [], [] if dense else hits) == hits
    assert merge_results([], []) == []


@pytest.mark.django_db
def test_hybrid_dense_only_hit_can_outrank_best_weak_lexical_hit():
    collection = Collection.objects.create(name="Fusion fixture")
    document = Document.objects.create(
        collection=collection,
        title="notes",
        original_filename="notes.txt",
        file_type="txt",
        sha256="f" * 64,
    )
    dense = DocumentChunk.objects.create(
        document=document, chunk_index=0, text="Rotate credentials monthly."
    )
    weak = DocumentChunk.objects.create(
        document=document,
        chunk_index=1,
        text="The security newsletter has a blue cover.",
    )

    class Provider:
        def embed_query(self, text):
            return [0.1]

    class Store:
        def search(self, **kwargs):
            return [VectorSearchResult(chunk_id=dense.id, score=0.3)]

    outcome = retrieve(
        "security",
        collection=collection.name,
        mode="hybrid",
        top_k=2,
        rerank=False,
        embedding_provider=Provider(),
        vector_store=Store(),
    )
    # Equal rank-one contributions tie; documented dense-first ordering applies.
    # The weak lexical candidate's normalized score of 1.0 gives it no advantage.
    assert [x.chunk.id for x in outcome.chunks] == [dense.id, weak.id]
    assert outcome.strategy == "hybrid"
    assert outcome.chunks[0].score == outcome.chunks[1].score == pytest.approx(1 / 61)
