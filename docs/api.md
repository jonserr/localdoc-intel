# API

The API is single-user and has no authentication. The default Compose deployment publishes the frontend and API on loopback only. The frontend forwards GET and POST requests from `/api/backend/...` to Django's `/api/.../` routes.

## Endpoints

| Method and path | Behavior |
|---|---|
| `GET /api/health/` | Database readiness; HTTP 200 when connected, 503 otherwise. |
| `GET /api/status/` | Service/model availability, feature flags, worker availability, and runtime limits. |
| `GET /api/stats/` | Corpus totals, latest document, file-type counts, text-ingestion counts, and vector-indexing counts. |
| `GET /api/settings/` | Configured service URLs, models, feature flags, runtime limits, `vector_min_score`, and application `version`. |
| `GET /api/collections/` | Collections and document counts. |
| `GET /api/documents/` | Documents; filters: `search`, `collection`, `file_type`, and text-ingestion `status`. |
| `GET /api/documents/{id}/` | Document, parser/provenance metadata, and indexing state. |
| `POST /api/documents/upload/` | Multipart `files` (or `file`), optional `collection`, `chunk_size`, and `overlap`; per-file results and errors. |
| `POST /api/documents/ingest-folder/` | Ingest a path visible to the backend; JSON `path`, optional `collection`, `chunk_size`, and `overlap`. |
| `POST /api/documents/{id}/reindex/` | Re-dispatch vector indexing for existing chunks; HTTP 202 with the updated document. |
| `GET /api/documents/{id}/chunks/` | Stored chunks with provenance and embedding IDs. |
| `GET /api/chunks/` | Chunk list; filters: `document_id`, `collection`, and `search`. |
| `POST /api/chat/query/` | Retrieve, generate or fall back, validate citation references, and persist chat history. |
| `GET /api/chat/history/` | Saved questions/answers; filters: `collection` and `retrieval_mode`. |
| `POST /api/evaluations/run/` | Synchronous evaluation using the configured demo questions, generation, and local judging. |
| `GET /api/evaluations/` | Stored evaluation metrics, strategy, configuration, and reproducibility fields. |

The document viewset also exposes DRF create/update/delete operations directly on Django. The frontend proxy currently exports GET and POST only; other methods are not proxied. Document deletion is not a complete archival purge of source files or external vector data.

## Text ingestion and vector indexing

A document's `status` describes text ingestion: `uploaded`, `processing`, `indexed`, or `failed`. An `indexed` document has stored chunks available to lexical retrieval; that does not imply vector indexing succeeded.

The separate `vector_indexing` field is `not_requested`, `disabled`, `queued`, `running`, `succeeded`, or `failed`. Older documents without lifecycle metadata return `not_requested`. Indexing errors are recorded in document metadata. Reindexing reuses stored chunks; it does not reparse the original document.

`GET /api/stats/` includes `documents_by_vector_indexing` counts for `queued`, `running`, `succeeded`, and `failed`. `GET /api/status/` includes a top-level `celery_worker` object with `available`, `enabled`, `workers`, and an optional `error`. Its aggregate `status` reflects the main service probes; inspect worker availability separately.

Document metadata includes `offset_basis`: `source_bytes`, `extracted_text`, or `none`. Consult it before interpreting chunk byte ranges. Existing documents are not automatically backfilled; re-ingestion records the new provenance metadata.

## Chat response contract

Example request:

```json
{"question":"What should be validated before deployment?","retrieval_mode":"hybrid","top_k":5,"rerank":true}
```

An optional `collection` scopes retrieval. Modes are `vector`, `hybrid`, and `metadata-filtered`; `top_k` is 1–20. Metadata filtering is available in the Python retrieval service; the chat request serializer does not expose arbitrary metadata-filter dictionaries.

The response contains `id`, `answer`, `citations`, and `metadata`. Each citation includes source number, document/chunk IDs, document title, page/line range, score, retrieval source, and preview.

Response metadata includes:

- `retrieval_mode`: requested mode; `retrieval_strategy`: actual `vector`, `hybrid`, or `bm25` strategy.
- `retrieval_fallback_reason`: why dense search was disabled, failed, or returned no usable results.
- `retrieval_top_k`, `rerank`, `embedding_model`, and `llm_model`.
- `answer_mode`: `generated`, `extractive`, or `no_results`; `generation_error` when applicable.
- `citation_status`: `valid`, `missing`, `invalid_references`, `extractive`, or `not_applicable`.
- `cited_sources` and `invalid_citations`: markers seen by validation, including rejected generated markers when fallback occurs.
- `retrieval_latency_ms` and total `latency_ms`.

Citation validation checks reference structure, not semantic support. Invalid/missing references cause extractive fallback. No retrieved passages produce `no_results` without generation. The history endpoint stores the answer and summary fields; it does not reproduce the complete original response metadata and citation objects.

## Evaluation response contract

```json
{"name":"Manual evaluation","mode":"hybrid","top_k":5,"rerank":true}
```

The endpoint uses `data/demo_questions.json` (mounted as `/data/demo_questions.json` in Docker). The management command supports alternate question files, collection scoping, and retrieval-only runs.

Runs serialize recall/MRR, expected-term coverage, lexical groundedness, answer-quality score, latency, and their question counts. `no_results_precision` is the unrelated-query rejection rate: the fraction of questions labeled `expect_no_results` that returned no passages. `no_results_question_count` is its denominator. The field name predates the rename and is kept for compatibility. When a denominator is zero, the UI shows **n/a**, even though the stored numeric default is zero.

Reproducibility fields include `retrieval_mode`, `retrieval_strategy`, `fallback_reason`, `top_k`, `rerank`, `embedding_model`, `llm_model`, `answer_judge_model`, `corpus_hash`, `corpus_document_count`, `chunk_hash`, `corpus_chunk_count`, `question_set_hash`, `question_set_path`, `revision`, and `config`. `corpus_hash` covers source bytes; `chunk_hash` covers the chunks retrieval saw plus the ingestion settings that produced them, so re-chunking the same bytes changes it. Runs recorded before 1.1.0 return empty strings for text identity fields and `null` for `top_k`, `rerank`, `corpus_document_count`, and `corpus_chunk_count`. The UI shows **Not recorded** for these values. The Evaluations page lets users inspect a selected run's metrics and expand its reproducibility details. See [Evaluation](evaluation.md) for definitions and limitations.

`config` includes the execution-time `vector_min_score`, `vector_search_enabled`,
`answer_generation_enabled`, and `retrieval_only` values, plus actual-strategy
counts. These keys are absent on older runs and must not be replaced with
current settings when displaying history.

Hybrid responses with both dense and lexical hits use reciprocal rank fusion scores, `sum(1 / (60 + rank))`. Single-provider responses keep their original score scale. Citation `retrieval_source` describes the hit's provenance; a dense-only hit in a fused response still has an RRF score. Scores are not probabilities or comparable across these strategies. New evaluation runs record the configured fusion policy and rank constant in `config`.
