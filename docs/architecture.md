# Architecture

LocalDoc Intel combines a Next.js frontend, Django REST API, PostgreSQL metadata store, Redis broker, Celery worker, Qdrant vector index, and Ollama model runtime. The default Docker ports are loopback-only; internal storage services have no published host ports. This is a single-user application, with local processing determined by its configured service URLs.

## Source of truth and processing

PostgreSQL stores documents, extracted chunks, chat history, and evaluation runs. Original files live in local media storage. Qdrant is a derived vector index; its availability and indexing state are separate from whether text has been ingested successfully. Keyword retrieval reads stored chunks from Postgres.

The ingestion layer parses each input, determines the coordinate basis, chunks text, and stores results. `offset_basis` identifies original UTF-8 bytes, transformed extracted text, or unavailable offsets. PDFs/OCR preserve page information. Re-ingesting old documents records the new provenance fields; there is no automatic backfill.

The optional C++ chunker is built in a separate Linux image stage, tested with CTest, and installed as `/usr/local/bin/localdoc_chunker`. `LOCALDOC_CHUNKER_PATH` points to that location. It remains visible when development source directories are bind-mounted. Eligible text/code files strictly larger than 4 MiB use its binary offset records; failures use the Python path. Both implementations use CRLF, CR, and LF line boundaries.

## Indexing lifecycle

Text-ingestion status and vector-indexing state serve different purposes. A document can be text-indexed and keyword-searchable while its vector index is queued or failed.

With indexing enabled, the lifecycle is `queued → running → succeeded`, with transient failures returning to `queued` for retry and exhausted retries recorded as `failed`. Disabled indexing is explicit. Parsing, OCR, format conversion and chunking finish before ingestion opens its write transaction. Collection/document/chunk writes and indexing-state updates commit atomically. Both synchronous indexing and Celery dispatch run through `transaction.on_commit`, after the outermost transaction commits; rolling back cancels them. Synchronous indexing still completes before ingestion returns when there is no enclosing transaction. A broker-dispatch failure triggers inline indexing; a reachable broker with no worker leaves work queued. The status endpoint probes workers separately. The reindex endpoint and detail-page action retry indexing of existing chunks.

## Retrieval and answers

Embedding providers, vector stores, and rerankers are injectable protocols. `retrieve()` returns `RetrievalOutcome`, including the requested mode, actual strategy, fallback reason, and result counts. The compatibility wrapper `retrieve_chunks()` returns just the chunks.

The lexical path ranks the full matching set, filters zero scores, and drops terms ubiquitous in sufficiently large scoped corpora. Dense search uses the configurable `VECTOR_MIN_SCORE`, default `0.0`; there is no calibrated corpus-independent relevance threshold. These decisions and their limits are described in [RAG design](rag_design.md).

Generation receives numbered evidence and validates returned citation references. Empty retrieval bypasses generation; model failures or invalid references produce an extractive response. Structural citation validity does not establish semantic grounding.

## Evaluation and verification

Evaluation runs persist aggregate metrics plus model, data, and revision identity. The UI exposes the unrelated-query rejection rate with its denominator and reproducibility details for historical runs. Benchmark reports count actual strategies and fallback reasons, so requested mode names cannot conceal a degraded run.

The backend image includes the root release-check tests and their scripts/metadata. `/backend` aliases `/app`, preserving the project layout for the root pytest configuration while maintaining the existing development mount. `make test` runs both backend and root tests with the packaged C++ binary required. Automated tests use controlled local dependencies and no live model inference.

Two stacks share the same images. The development stack mounts the sources and runs the development servers. The runtime images (`compose.prod.yml`) contain only the application and its runtime dependencies: gunicorn serves Django, the Next.js standalone server serves the frontend, static files are collected during the build, and both containers run as a non-root user. `compose.offline.yml` runs those runtime images on an internal Compose network to prove that the application works with no route off the host.

Vendor telemetry is disabled in configuration: `QDRANT__TELEMETRY_DISABLED=true` and `NEXT_TELEMETRY_DISABLED=1`. Cloud-served Ollama models are rejected in configuration and reported by the status endpoint. Disabling Ollama's cloud features on the host is what enforces that.

The system is designed for a personal document corpus. Full lexical scoring, synchronous parsing, and sequential model calls are explicit scaling boundaries. Native Windows host workflows, large concurrent workloads, semantic citation entailment, and OCR accuracy across real-world scans are not established by the automated suite.
