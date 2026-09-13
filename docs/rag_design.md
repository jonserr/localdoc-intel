# RAG design

## Ingestion and provenance

Files are validated, hashed, parsed, and converted into stored chunks. Images and scanned PDF pages can use local OCR. PDFs preserve page references; transformed inputs record an extracted-text coordinate basis rather than implying their text offsets address the original file.

Python and C++ share CRLF, CR, and LF line boundaries. Unicode paragraph separators, form feed, vertical tab, and NEL remain within a line. Chunk byte offsets describe UTF-8 bytes, and `offset_basis` specifies whether those are original source bytes or extracted text. Inputs altered by decoding replacement or null sanitization cannot claim unchanged raw-byte provenance.

The C++ fast path applies only to eligible files larger than 4 MiB. It emits offsets; Python reconstructs text and token counts from source bytes. Missing/failed/invalid binary output uses the Python implementation. The recorded performance is for the chunker pipeline, not parsing, OCR, embedding, or total ingestion.

## Retrieval policy

`retrieve()` returns chunks and a `RetrievalOutcome` describing what ran. Callers that display or benchmark a strategy should use this outcome, not the chunk-only compatibility wrapper.

1. Apply collection and supported metadata scope.
2. Attempt dense retrieval when vector search is enabled. Discard results below `VECTOR_MIN_SCORE`.
3. For hybrid requests with both retrievers active, fuse dense and lexical ranks using equal-weight Reciprocal Rank Fusion (RRF). Other modes use lexical fallback when no dense results survive or dense search fails/is disabled.
4. Rank all lexical candidates rather than truncating by insertion order. Zero-score matches are excluded; there is no arbitrary-document fallback. With at least five chunks in scope, terms present in at least 90% of chunks are ignored as uninformative.
5. Optionally rerank, then apply `top_k`. The implemented reranker is lexical; it is not a neural cross-encoder.
6. Return the actual strategy and fallback reason alongside results. `metadata-filtered` describes a scoped request, not a distinct ranking algorithm.

When both result lists are nonempty, each hit receives `sum(1 / (60 + rank))`, using one-based ranks and one contribution per retriever. A hit found by both gets both contributions. No raw cosine score is compared with a normalized BM25 score. Equal fused scores preserve dense-first encounter order, then lexical order; this deterministic tie-break does not establish semantic relevance. The fixed rank constant is 60, with equal weights and the existing top-k candidate depth per retriever; it has not been tuned to the evaluation corpus.

Single-provider results retain their native scores: cosine for dense retrieval, relative `score / max_score` for BM25. In a fused list every returned score is an RRF score, while each hit's `source` still records dense-only, BM25-only, or shared provenance. Internal metadata records `fusion`, `rrf_rank_constant`, and `retriever_ranks`. Optional keyword reranking runs after fusion and can change its order. These scores are ranking signals, not probabilities; the dense floor is applied before fusion, not to RRF scores. Rank fusion does not itself reject a weak lexical match.

The published hybrid measurements predate RRF. Rerun the frozen evaluation set before claiming a quality improvement from this change.

The default dense floor remains `0.0`. The 0.37 example in the evaluation table is a corpus-specific experiment based on only three unrelated questions, not a general recommendation. Dense nearest-neighbour results may therefore exist for unrelated questions. Larger labeled datasets are needed to calibrate rejection behavior. Full lexical scoring also limits corpus scale; a future indexed candidate stage must be evaluated for recall before replacing it.

## Generation and citation handling

No retrieved chunks means `answer_mode=no_results`; the model is not called. Otherwise the model receives numbered source context and instructions to answer from that evidence. Disabled/unavailable generation returns relevant source excerpts.

Generated answers must contain references to supplied sources. Missing or out-of-range references cause an extractive fallback and an explicit validation status. A valid `[1]` proves only that source 1 existed; it does not prove the neighboring sentence is supported. Semantic support requires a separate judge or manual annotation.

## Evaluation boundaries

Recall/MRR measure document retrieval on labeled questions. Expected-term coverage and lexical groundedness inspect retrieved text, not model-claim entailment. The unrelated-query rejection rate reports correct abstention on questions labeled unrelated, with its denominator shown in the UI. A local judge provides a separate, fallible answer-quality score.

Runs save configuration, strategy, model identifiers, data hashes, and revision when available. Unavailable identity fields are displayed as not recorded. See [Evaluation](evaluation.md) and [the evaluation corpus](eval_corpus.md) for reproduction steps and sample-size limits.
