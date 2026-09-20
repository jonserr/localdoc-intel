export type RetrievalMode = "vector" | "hybrid" | "metadata-filtered";

export type Collection = {
  id: number;
  name: string;
  description: string;
  document_count: number;
  created_at: string;
  updated_at: string;
};

export type DocumentStatus = "uploaded" | "processing" | "indexed" | "failed";

export type VectorIndexingState =
  | "not_requested"
  | "disabled"
  | "queued"
  | "running"
  | "succeeded"
  | "failed";

export type DocumentRecord = {
  id: number;
  collection: Collection;
  title: string;
  original_filename: string;
  file_type: string;
  sha256: string;
  source_path: string;
  metadata: Record<string, unknown>;
  status: DocumentStatus;
  vector_indexing?: VectorIndexingState;
  error_message: string;
  chunk_count: number;
  byte_size: number;
  created_at: string;
  updated_at: string;
  last_indexed_at: string | null;
};

export type DocumentChunk = {
  id: number;
  document: number;
  document_title: string;
  document_collection: string;
  chunk_index: number;
  text: string;
  text_preview: string;
  page: number | null;
  start_line: number | null;
  end_line: number | null;
  byte_start: number | null;
  byte_end: number | null;
  token_count: number;
  embedding_id: string;
  created_at: string;
};

export type StatsResponse = {
  total_documents: number;
  total_chunks: number;
  total_collections: number;
  indexed_collections: number;
  latest_ingestion_status: string;
  latest_document: DocumentRecord | null;
  documents_by_status: Record<string, number>;
  documents_by_vector_indexing?: Record<string, number>;
  documents_by_file_type: Record<string, number>;
};

export type SettingsResponse = {
  ollama_base_url: string;
  embedding_model: string;
  llm_model: string;
  eval_judge_model: string;
  qdrant_url: string;
  redis_url: string;
  privacy: string;
  vector_min_score?: number;
  features: Record<string, string>;
  runtime: RuntimeProfile;
  version: string;
};

export type Citation = {
  source_number: number;
  document: string;
  document_id: number;
  chunk_id: number;
  page: number | null;
  start_line: number | null;
  end_line: number | null;
  score: number;
  retrieval_source: string;
  text_preview: string;
};

export type AnswerMode =
  | "generated"
  | "extractive"
  | "no_results"
  | "collection_analysis"
  | "review_references";

export type CitationStatus =
  | "valid"
  | "missing"
  | "invalid_references"
  | "extractive"
  | "not_applicable";

export type ChatResponse = {
  id: number;
  answer: string;
  question?: string;
  citations: Citation[];
  inventory?: {
    name: string;
    // Every reviewed spelling when values were merged, display name included.
    variants?: string[];
    source_number?: number;
    evidence?: string;
    matches?: { source_number: number; evidence: string }[];
  }[];
  metadata: {
    retrieval_mode: RetrievalMode;
    retrieval_top_k: number;
    embedding_model: string;
    llm_model: string;
    answer_mode: AnswerMode;
    generation_error: string;
    retrieval_strategy?: "vector" | "hybrid" | "bm25" | "collection_review";
    retrieval_fallback_reason?: string;
    analysis_routing_error?: string;
    analysis_id?: string;
    analysis_status?:
      | "queued"
      | "running"
      | "complete"
      | "partial"
      | "failed"
      | "cancelled";
    answer_cached?: boolean;
    analysis_cached?: boolean;
    analysis_cached_units?: number;
    analysis_collection?: string;
    analysis_context_tokens?: number;
    analysis_batch_elapsed_seconds?: number | null;
    analysis_units_processed?: number;
    analysis_units_total?: number;
    analysis_missing_document_ids?: number[];
    analysis_inventory_count?: number | null;
    /** Extracted values a restriction applies to; 0 when there is none. */
    analysis_filter_total?: number;
    /** Extracted values with no filter verdict yet. They are never results. */
    analysis_filter_pending?: number;
    retrieved_source_count?: number;
    collection_document_count?: number | null;
    collection_chunk_count?: number | null;
    citation_status?: CitationStatus;
    cited_sources?: number[];
    invalid_citations?: number[];
    retrieval_latency_ms: number;
    latency_ms: number;
    rerank?: boolean;
  };
};

export type ServiceStatus = {
  available: boolean;
  error?: string;
  collections?: string[];
  target_collection?: string;
  target_collection_exists?: boolean;
  embedding_model?: string;
  embedding_model_pulled?: boolean;
  llm_model?: string;
  llm_model_pulled?: boolean;
  /** Entries Ollama serves from its cloud, listed locally. */
  cloud_models?: string[];
  /** Configured models that Ollama would serve remotely. */
  configured_cloud_models?: string[];
};

export type SystemStatusResponse = {
  status: "ok" | "degraded";
  celery_worker?: {
    available: boolean;
    enabled: boolean;
    workers: string[];
    error?: string;
  };
  services: {
    database: ServiceStatus;
    redis: ServiceStatus;
    qdrant: ServiceStatus;
    ollama: ServiceStatus;
  };
  features: {
    vector_indexing: boolean;
    vector_search: boolean;
    answer_generation: boolean;
    async_indexing: boolean;
    ocr: boolean;
  };
  runtime: RuntimeProfile;
};

export type RuntimeProfile = {
  cpu_count: number;
  memory_mb: number | null;
  ingest_max_workers: number;
  celery_concurrency: number;
  ocr_pdf_dpi: number;
  ocr_timeout_seconds: number;
  active: {
    ingestion_max_workers: number;
    celery_worker_concurrency: number;
    ocr_pdf_dpi: number;
    ocr_timeout_seconds: number;
  };
};

export type ChatQueryRequest = {
  question: string;
  analysis_scope?: "auto" | "retrieved" | "collection";
  collection?: string;
  retrieval_mode: RetrievalMode;
  top_k: number;
  rerank: boolean;
  review_id?: string;
};

export type ChatHistoryItem = {
  id: number;
  question: string;
  answer: string;
  retrieval_mode: RetrievalMode;
  retrieval_top_k: number;
  collection: string;
  citation_count: number;
  latency_ms: number;
  created_at: string;
};

export type EvaluationRun = {
  id: number;
  name: string;
  recall_at_k: number;
  mean_reciprocal_rank: number;
  /** Expected key terms found in retrieved text, not citation accuracy. */
  expected_term_coverage: number;
  /** Lexical proxy over retrieved text, not a check of answer claims. */
  groundedness_score: number;
  answer_quality_score: number;
  judged_answer_count: number;
  answer_judge_model: string;
  average_latency_ms: number;
  question_count: number;
  labeled_question_count?: number;
  coverage_question_count?: number;
  no_results_precision?: number;
  no_results_question_count?: number;
  /** Mode requested by the caller; empty or null when not recorded. */
  retrieval_mode?: RetrievalMode | "" | null;
  /** Algorithm that actually ran; differs from retrieval_mode on fallback. */
  retrieval_strategy?: "vector" | "hybrid" | "bm25" | "mixed" | "";
  fallback_reason?: string;
  /** Null for runs recorded before 1.1.0. */
  top_k?: number | null;
  rerank?: boolean | null;
  embedding_model?: string;
  llm_model?: string;
  corpus_hash?: string;
  corpus_document_count?: number | null;
  /** Identity of the chunks retrieval saw; source bytes alone do not fix it. */
  chunk_hash?: string;
  corpus_chunk_count?: number | null;
  question_set_hash?: string;
  question_set_path?: string;
  revision?: string;
  config?: {
    vector_min_score?: number | null;
    vector_search_enabled?: boolean | null;
    answer_generation_enabled?: boolean | null;
    retrieval_only?: boolean | null;
    [key: string]: unknown;
  };
  created_at: string;
};

export type EvaluationRunRequest = {
  name: string;
  top_k: number;
  mode: RetrievalMode;
  rerank: boolean;
};

export type UploadResponse = {
  detail: string;
  received_files: number;
  documents: {
    document: DocumentRecord;
    created: boolean;
    chunks_created: number;
    chunks_updated: number;
  }[];
  errors: {
    filename?: string;
    path?: string;
    error: string;
  }[];
};

export type ApiErrorBody = Record<string, unknown> | string | null;
