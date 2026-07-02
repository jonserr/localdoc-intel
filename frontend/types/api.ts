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

export type AnswerMode = "generated" | "extractive" | "no_results";

export type ChatResponse = {
  id: number;
  answer: string;
  citations: Citation[];
  metadata: {
    retrieval_mode: RetrievalMode;
    retrieval_top_k: number;
    embedding_model: string;
    llm_model: string;
    answer_mode: AnswerMode;
    generation_error: string;
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
};

export type SystemStatusResponse = {
  status: "ok" | "degraded";
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
  collection?: string;
  retrieval_mode: RetrievalMode;
  top_k: number;
  rerank: boolean;
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
  citation_coverage: number;
  groundedness_score: number;
  answer_quality_score: number;
  judged_answer_count: number;
  answer_judge_model: string;
  average_latency_ms: number;
  question_count: number;
  labeled_question_count?: number;
  coverage_question_count?: number;
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
