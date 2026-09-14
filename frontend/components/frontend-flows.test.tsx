import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mockApi = vi.hoisted(() => ({
  stats: vi.fn(),
  status: vi.fn(),
  settings: vi.fn(),
  collections: vi.fn(),
  documents: vi.fn(),
  document: vi.fn(),
  documentChunks: vi.fn(),
  uploadDocuments: vi.fn(),
  chatQuery: vi.fn(),
  chatActiveAnalyses: vi.fn(),
  chatAnalysisControl: vi.fn(),
  chatAnalysis: vi.fn(),
  chatAnalysisReferences: vi.fn(),
  chatHistory: vi.fn(),
  evaluations: vi.fn(),
  runEvaluation: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  api: mockApi,
  getErrorMessage: (error: unknown) =>
    error instanceof Error ? error.message : String(error),
}));

import { ChatClient } from "@/components/chat/chat-client";
import { DashboardClient } from "@/components/dashboard/dashboard-client";
import { DocumentsClient } from "@/components/documents/documents-client";
import { UploadClient } from "@/components/documents/upload-client";
import { EvaluationsClient } from "@/components/evaluations/evaluations-client";

const statusResponse = {
  status: "ok",
  services: {
    database: { available: true },
    redis: { available: true },
    qdrant: { available: true, target_collection_exists: true },
    ollama: {
      available: true,
      embedding_model_pulled: true,
      llm_model_pulled: true,
    },
  },
  features: {
    vector_indexing: true,
    vector_search: true,
    answer_generation: true,
    async_indexing: true,
    ocr: true,
  },
};

const documentRecord = {
  id: 7,
  collection: {
    id: 1,
    name: "Demo",
    description: "",
    document_count: 1,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  },
  title: "receipt.pdf",
  original_filename: "receipt.pdf",
  file_type: "pdf",
  sha256: "a".repeat(64),
  source_path: "/data/demo_intake/receipt.pdf",
  metadata: { parser: "pypdf+tesseract" },
  status: "indexed",
  error_message: "",
  chunk_count: 3,
  byte_size: 2048,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-02T00:00:00Z",
  last_indexed_at: "2026-01-02T00:00:00Z",
};

const evaluationRun = {
  id: 3,
  name: "Receipt eval",
  recall_at_k: 0.75,
  mean_reciprocal_rank: 0.5,
  expected_term_coverage: 0.8,
  retrieval_mode: "hybrid",
  retrieval_strategy: "bm25",
  fallback_reason: "vector search disabled (VECTOR_SEARCH_ENABLED=false)",
  groundedness_score: 0.7,
  answer_quality_score: 0.9,
  judged_answer_count: 8,
  answer_judge_model: "local-judge",
  average_latency_ms: 125,
  question_count: 8,
  labeled_question_count: 4,
  coverage_question_count: 4,
  created_at: "2026-01-03T00:00:00Z",
};

beforeEach(() => {
  Object.values(mockApi).forEach((fn) => fn.mockReset());
  mockApi.status.mockResolvedValue(statusResponse);
  mockApi.collections.mockResolvedValue([]);
  mockApi.chatHistory.mockResolvedValue([]);
  mockApi.chatActiveAnalyses.mockResolvedValue([]);
  mockApi.evaluations.mockResolvedValue([]);
});

describe("dashboard", () => {
  it("renders backend summaries and next steps", async () => {
    mockApi.stats.mockResolvedValue({
      total_documents: 1,
      total_chunks: 3,
      total_collections: 1,
      indexed_collections: 1,
      latest_ingestion_status: "indexed",
      latest_document: documentRecord,
      documents_by_status: { indexed: 1 },
      documents_by_file_type: { pdf: 1 },
    });
    mockApi.documents.mockResolvedValue([documentRecord]);
    mockApi.chatHistory.mockResolvedValue([
      {
        id: 1,
        question: "What dates are visible?",
        answer: "Jan 2",
        retrieval_mode: "hybrid",
        retrieval_top_k: 5,
        collection: "Demo",
        citation_count: 1,
        latency_ms: 90,
        created_at: "2026-01-03T00:00:00Z",
      },
    ]);
    mockApi.evaluations.mockResolvedValue([evaluationRun]);

    render(<DashboardClient />);

    expect(
      await screen.findByText("Local document workspace"),
    ).toBeInTheDocument();
    expect(screen.getByText("make demo-data")).toBeInTheDocument();
    expect(screen.getAllByText("receipt.pdf")[0]).toBeInTheDocument();
  });
});

describe("documents", () => {
  it("renders populated document rows", async () => {
    mockApi.documents.mockResolvedValue([documentRecord]);

    render(<DocumentsClient />);

    expect((await screen.findAllByText("receipt.pdf"))[0]).toBeInTheDocument();
    expect(
      screen.getByText("/data/demo_intake/receipt.pdf"),
    ).toBeInTheDocument();
    expect(screen.getByText("2.0 KB")).toBeInTheDocument();
  });

  it("renders empty and error states", async () => {
    mockApi.documents.mockResolvedValueOnce([]);
    const { unmount } = render(<DocumentsClient />);

    expect(await screen.findByText("No documents indexed")).toBeInTheDocument();
    unmount();

    mockApi.documents.mockRejectedValueOnce(new Error("Backend down"));
    render(<DocumentsClient />);

    expect(
      await screen.findByText("Could not load documents"),
    ).toBeInTheDocument();
    expect(screen.getByText("Backend down")).toBeInTheDocument();
  });
});

describe("intake", () => {
  it("explains local intake commands and editable questions", () => {
    render(<UploadClient />);

    expect(screen.getByText("make demo-data")).toBeInTheDocument();
    expect(screen.getByText("make ingest-demo")).toBeInTheDocument();
    expect(
      screen.getAllByText("data/demo_questions.json")[0],
    ).toBeInTheDocument();
    expect(screen.getByText(".pdf")).toBeInTheDocument();
  });

  it("shows green upload progress after files are selected", async () => {
    mockApi.uploadDocuments.mockResolvedValue({
      detail: "Uploaded and indexed 1 document.",
      received_files: 1,
      documents: [
        {
          document: documentRecord,
          created: true,
          chunks_created: 3,
          chunks_updated: 0,
        },
      ],
      errors: [],
    });

    render(<UploadClient />);

    fireEvent.change(screen.getByLabelText("Choose files to upload"), {
      target: {
        files: [
          new File(["receipt text"], "receipt.txt", { type: "text/plain" }),
        ],
      },
    });

    expect(screen.getByText("1 file ready for intake.")).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toHaveAttribute(
      "aria-valuenow",
      "12",
    );

    fireEvent.click(screen.getByRole("button", { name: /start upload/i }));

    expect(
      await screen.findByText("Uploaded and indexed 1 document."),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByRole("progressbar")).toHaveAttribute(
        "aria-valuenow",
        "100",
      ),
    );
  });
});

describe("chat", () => {
  it("submits a question and renders citations", async () => {
    mockApi.chatQuery.mockResolvedValue({
      id: 9,
      answer: "The total is 12.34 [1]",
      citations: [
        {
          source_number: 1,
          document: "receipt.pdf",
          document_id: 7,
          chunk_id: 11,
          page: 1,
          start_line: null,
          end_line: null,
          score: 0.92,
          retrieval_source: "hybrid",
          text_preview: "Total 12.34",
        },
      ],
      metadata: {
        retrieval_mode: "hybrid",
        retrieval_top_k: 5,
        retrieved_source_count: 1,
        collection_document_count: 1158,
        collection_chunk_count: 2565,
        embedding_model: "embed",
        llm_model: "llm",
        answer_mode: "generated",
        generation_error: "",
        retrieval_strategy: "bm25",
        retrieval_fallback_reason:
          "vector search disabled (VECTOR_SEARCH_ENABLED=false)",
        citation_status: "valid",
        cited_sources: [1],
        invalid_citations: [],
        retrieval_latency_ms: 30,
        latency_ms: 80,
        rerank: true,
      },
    });

    render(<ChatClient />);

    fireEvent.change(
      screen.getByPlaceholderText("Ask a question about your documents..."),
      { target: { value: "What is the total?" } },
    );
    fireEvent.click(screen.getByRole("button", { name: /send/i }));

    expect(
      await screen.findByText("The total is 12.34 [1]"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Retrieved source chunks: 1. Search scope: 1158 documents, 2565 stored chunks. Retrieved passages are a partial sample, not a complete collection review.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("Total 12.34")).toBeInTheDocument();
    expect(screen.getByText("score 0.92")).toBeInTheDocument();
  });

  it("renders backend chat errors", async () => {
    mockApi.chatQuery.mockRejectedValue(new Error("Ollama unavailable"));

    render(<ChatClient />);

    fireEvent.change(
      screen.getByPlaceholderText("Ask a question about your documents..."),
      { target: { value: "Question?" } },
    );
    fireEvent.click(screen.getByRole("button", { name: /send/i }));

    expect(await screen.findByText("Ollama unavailable")).toBeInTheDocument();
  });
});

describe("evaluations", () => {
  it("renders evaluation summary and question source", async () => {
    mockApi.evaluations.mockResolvedValue([evaluationRun]);

    render(<EvaluationsClient />);

    // The run name appears in the summary heading and the history table
    expect((await screen.findAllByText("Receipt eval"))[0]).toBeInTheDocument();
    expect(
      screen.getAllByText("data/demo_questions.json")[0],
    ).toBeInTheDocument();
    expect(screen.getAllByText("75%")[0]).toBeInTheDocument();
    expect(screen.getAllByText("local-judge")[0]).toBeInTheDocument();
  });
});

describe("retrieval and citation reporting", () => {
  it("shows the strategy that actually ran and the citation verdict", async () => {
    mockApi.chatQuery.mockResolvedValue({
      id: 10,
      answer: "Validate migrations [1]",
      citations: [
        {
          source_number: 1,
          document: "runbook.md",
          document_id: 7,
          chunk_id: 12,
          page: null,
          start_line: 1,
          end_line: 4,
          score: 0.8,
          retrieval_source: "bm25",
          text_preview: "Validate migrations",
        },
      ],
      metadata: {
        retrieval_mode: "vector",
        retrieval_top_k: 5,
        embedding_model: "embed",
        llm_model: "llm",
        answer_mode: "generated",
        generation_error: "",
        retrieval_strategy: "bm25",
        retrieval_fallback_reason: "vector search returned no results",
        citation_status: "valid",
        cited_sources: [1],
        invalid_citations: [],
        retrieval_latency_ms: 20,
        latency_ms: 60,
        rerank: false,
      },
    });

    render(<ChatClient />);

    fireEvent.change(
      screen.getByPlaceholderText("Ask a question about your documents..."),
      { target: { value: "What is validated?" } },
    );
    fireEvent.click(screen.getByRole("button", { name: /send/i }));

    expect(await screen.findByText("vector \u2192 bm25")).toBeInTheDocument();
    expect(
      screen.getByText("citations reference supplied sources"),
    ).toBeInTheDocument();
  });

  it("reports a rejected invalid citation as an extractive fallback", async () => {
    mockApi.chatQuery.mockResolvedValue({
      id: 11,
      answer: "Local answer generation is unavailable...",
      citations: [],
      metadata: {
        retrieval_mode: "hybrid",
        retrieval_top_k: 5,
        embedding_model: "embed",
        llm_model: "llm",
        answer_mode: "extractive",
        generation_error: "Model cited sources that were not supplied: [99]",
        retrieval_strategy: "bm25",
        retrieval_fallback_reason: "",
        citation_status: "invalid_references",
        cited_sources: [99],
        invalid_citations: [99],
        retrieval_latency_ms: 20,
        latency_ms: 60,
        rerank: false,
      },
    });

    render(<ChatClient />);

    fireEvent.change(
      screen.getByPlaceholderText("Ask a question about your documents..."),
      { target: { value: "What is validated?" } },
    );
    fireEvent.click(screen.getByRole("button", { name: /send/i }));

    expect(
      await screen.findByText("invalid citations rejected"),
    ).toBeInTheDocument();
    expect(screen.getByText(/not supplied: \[99\]/)).toBeInTheDocument();
  });
});

describe("local-model privacy", () => {
  async function renderDashboardWithOllama(ollama: Record<string, unknown>) {
    mockApi.status.mockResolvedValue({
      ...statusResponse,
      services: { ...statusResponse.services, ollama },
    });
    mockApi.stats.mockResolvedValue({
      total_documents: 0,
      total_chunks: 0,
      total_collections: 0,
      indexed_collections: 0,
      latest_ingestion_status: "empty",
      latest_document: null,
      documents_by_status: {},
      documents_by_file_type: {},
      documents_by_vector_indexing: {},
    });
    mockApi.documents.mockResolvedValue([]);
    render(<DashboardClient />);
    return screen.findByText("Service status");
  }

  it("reports listed cloud entries without claiming they are used", async () => {
    await renderDashboardWithOllama({
      available: true,
      embedding_model_pulled: true,
      llm_model_pulled: true,
      cloud_models: ["glm-5.1:cloud", "gpt-oss:120b-cloud"],
      configured_cloud_models: [],
    });

    expect(
      await screen.findByText("cloud entries listed: 2 (not used)"),
    ).toBeInTheDocument();
  });

  it("flags a configured cloud model", async () => {
    await renderDashboardWithOllama({
      available: true,
      embedding_model_pulled: true,
      llm_model_pulled: true,
      cloud_models: ["glm-5.1:cloud"],
      configured_cloud_models: ["glm-5.1:cloud"],
    });

    expect(
      await screen.findByText("configured cloud model: glm-5.1:cloud"),
    ).toBeInTheDocument();
  });

  it("says so when no cloud entries exist", async () => {
    await renderDashboardWithOllama({
      available: true,
      embedding_model_pulled: true,
      llm_model_pulled: true,
      cloud_models: [],
      configured_cloud_models: [],
    });

    expect(await screen.findByText("no cloud entries")).toBeInTheDocument();
  });
});

describe("release status visibility", () => {
  it("separates successful text ingestion from failed vector indexing", async () => {
    mockApi.documents.mockResolvedValue([
      { ...documentRecord, vector_indexing: "failed" },
    ]);
    render(<DocumentsClient />);
    const failed = await screen.findByLabelText("Vector index: Failed");
    const row = failed.closest("tr")!;
    expect(within(row).getByText("indexed")).toBeInTheDocument();
    expect(
      within(row).getByRole("link", { name: "Review indexing failure" }),
    ).toHaveAttribute("href", "/documents/7");
  });

  it("does not invent an indexing success for older documents", async () => {
    mockApi.documents.mockResolvedValue([documentRecord]);
    render(<DocumentsClient />);
    expect(
      await screen.findByLabelText("Vector index: Not requested"),
    ).toBeInTheDocument();
  });

  it("shows dashboard vector counts separately from text ingestion", async () => {
    mockApi.stats.mockResolvedValue({
      total_documents: 7,
      total_chunks: 14,
      total_collections: 1,
      indexed_collections: 1,
      latest_ingestion_status: "indexed",
      latest_document: null,
      documents_by_status: { indexed: 7 },
      documents_by_file_type: { txt: 7 },
      documents_by_vector_indexing: {
        queued: 2,
        running: 1,
        succeeded: 3,
        failed: 1,
      },
    });
    mockApi.documents.mockResolvedValue([]);
    render(<DashboardClient />);
    expect(
      await screen.findByLabelText("Vector index: Failed (1)"),
    ).toBeInTheDocument();
    expect(
      screen.getByLabelText("Vector index: Queued (2)"),
    ).toBeInTheDocument();
    expect(
      screen.getByLabelText("Vector index: Succeeded (3)"),
    ).toBeInTheDocument();
  });

  it("reports dashboard totals and no invented judge score", async () => {
    mockApi.stats.mockResolvedValue({
      total_documents: 0,
      total_chunks: 0,
      total_collections: 0,
      indexed_collections: 0,
      latest_ingestion_status: "empty",
      latest_document: null,
      documents_by_status: {},
      documents_by_file_type: {},
      documents_by_vector_indexing: {},
    });
    mockApi.documents.mockResolvedValue([]);
    mockApi.chatHistory.mockResolvedValue(
      Array.from({ length: 5 }, (_, index) => ({
        id: index + 1,
        question: `Question ${index + 1}`,
        answer: "",
        retrieval_mode: "hybrid",
        retrieval_top_k: 5,
        collection: "",
        citation_count: 0,
        latency_ms: 10,
        created_at: "2026-01-03T00:00:00Z",
      })),
    );
    // Retrieval-only runs store a zero score with no judged answers
    mockApi.evaluations.mockResolvedValue(
      Array.from({ length: 6 }, (_, index) => ({
        ...evaluationRun,
        id: index + 1,
        name: `Run ${index + 1}`,
        answer_quality_score: 0,
        judged_answer_count: 0,
      })),
    );
    render(<DashboardClient />);

    const runs = (await screen.findByText("Evaluation runs")).parentElement!;
    await waitFor(() =>
      expect(within(runs).getByText("6")).toBeInTheDocument(),
    );
    const chats = screen.getByText("Chat queries").parentElement!;
    expect(within(chats).getByText("5")).toBeInTheDocument();
    expect(
      screen.getByText("latest run has no judge score"),
    ).toBeInTheDocument();
    expect(screen.queryByText(/0% judge score/)).not.toBeInTheDocument();
  });

  it("moves focus to the updated summary after Inspect run", async () => {
    mockApi.evaluations.mockResolvedValue([
      evaluationRun,
      { ...evaluationRun, id: 2, name: "Earlier run" },
    ]);
    render(<EvaluationsClient />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Inspect Earlier run" }),
    );
    expect(
      screen.getByRole("heading", { name: "Showing metrics for Earlier run" }),
    ).toHaveFocus();
  });

  it("lets a reviewer inspect historical run identity and matching metrics", async () => {
    mockApi.evaluations.mockResolvedValue([
      {
        ...evaluationRun,
        no_results_precision: 2 / 3,
        no_results_question_count: 3,
        corpus_hash: "a".repeat(64),
        question_set_hash: "b".repeat(64),
        revision: "new-revision",
        top_k: 5,
        rerank: true,
        embedding_model: "new-embed",
      },
      {
        ...evaluationRun,
        id: 2,
        name: "Earlier run",
        no_results_precision: 0,
        no_results_question_count: 3,
        revision: "old-revision",
        top_k: 2,
        rerank: false,
        embedding_model: "old-embed",
      },
    ]);
    render(<EvaluationsClient />);
    expect(
      await screen.findByText("Run details: Receipt eval"),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByText("Reproducibility details"));
    expect(screen.getByText("a".repeat(64))).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "Inspect Earlier run" }),
    );
    expect(screen.getByText("Run details: Earlier run")).toBeInTheDocument();
    expect(screen.getByText("old-revision")).toBeInTheDocument();
    expect(screen.getByText("old-embed")).toBeInTheDocument();
    expect(screen.getByText("Disabled")).toBeInTheDocument();
    const metric = screen
      .getByText("Unrelated-query rejection rate")
      .closest("div")!;
    expect(within(metric).getByText("0% (n=3)")).toBeInTheDocument();
  });

  it("does not present unrecorded pre-1.1.0 configuration as values", async () => {
    // API shape after migration 0005: unknown values are null or empty
    mockApi.evaluations.mockResolvedValue([
      {
        ...evaluationRun,
        id: 1,
        name: "Legacy run",
        retrieval_mode: "",
        retrieval_strategy: "",
        fallback_reason: "",
        top_k: null,
        rerank: null,
        corpus_document_count: null,
        corpus_hash: "",
        config: {},
      },
    ]);
    render(<EvaluationsClient />);
    await screen.findByText("Run details: Legacy run");
    const row = screen
      .getByRole("button", { name: "Inspect Legacy run" })
      .closest("tr")!;
    expect(within(row).getByText("Not recorded")).toBeInTheDocument();

    fireEvent.click(screen.getByText("Reproducibility details"));
    for (const label of [
      "Requested mode",
      "Actual strategy",
      "Top k",
      "Reranking",
      "Corpus documents",
      "Vector relevance floor",
      "Vector search",
      "Answer generation",
      "Evaluation scope",
    ]) {
      const item = screen.getByText(label).closest("div")!;
      expect(within(item).getByText("Not recorded")).toBeInTheDocument();
    }
    expect(screen.queryByText("Enabled")).not.toBeInTheDocument();
    expect(screen.queryByText("Disabled")).not.toBeInTheDocument();
  });

  it("labels a requested mode whose actual strategy was not recorded", async () => {
    mockApi.evaluations.mockResolvedValue([
      { ...evaluationRun, retrieval_mode: "vector", retrieval_strategy: "" },
    ]);
    render(<EvaluationsClient />);
    expect(
      await screen.findByText("vector (strategy not recorded)"),
    ).toBeInTheDocument();
  });

  it("does not show measured values before any evaluation run", async () => {
    mockApi.evaluations.mockResolvedValue([]);
    render(<EvaluationsClient />);
    await screen.findByText("No evaluation runs yet");
    expect(screen.getAllByText("n/a (no runs)")).toHaveLength(6);
    expect(screen.queryByText("0%")).not.toBeInTheDocument();
    expect(screen.queryByText("0.00")).not.toBeInTheDocument();
  });

  it("shows n/a and missing provenance for legacy runs", async () => {
    mockApi.evaluations.mockResolvedValue([evaluationRun]);
    render(<EvaluationsClient />);
    expect(
      await screen.findByText("n/a (no labeled negatives)"),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByText("Reproducibility details"));
    expect(screen.getAllByText("Not recorded").length).toBeGreaterThan(0);
  });
  it.each([0, 0.37])(
    "shows saved effective settings including floor %s",
    async (floor) => {
      mockApi.evaluations.mockResolvedValue([
        {
          ...evaluationRun,
          config: {
            vector_min_score: floor,
            vector_search_enabled: true,
            answer_generation_enabled: false,
            retrieval_only: true,
          },
        },
      ]);
      render(<EvaluationsClient />);
      await screen.findByText(`Run details: ${evaluationRun.name}`);
      fireEvent.click(screen.getByText("Reproducibility details"));
      for (const [label, value] of [
        ["Vector relevance floor", String(floor)],
        ["Vector search", "Enabled"],
        ["Answer generation", "Disabled"],
        ["Evaluation scope", "Retrieval only"],
      ]) {
        expect(
          within(screen.getByText(label).closest("div")!).getByText(value),
        ).toBeInTheDocument();
      }
    },
  );
});

const pendingReview = {
  id: 91,
  question: "List project names in the documents.",
  answer: "Reviewing the full collection.",
  citations: [],
  inventory: [],
  metadata: {
    retrieval_mode: "hybrid",
    retrieval_strategy: "collection_review",
    retrieval_top_k: 5,
    embedding_model: "embed",
    llm_model: "llm",
    answer_mode: "collection_analysis",
    generation_error: "",
    analysis_id: "review-1",
    analysis_status: "queued",
    analysis_units_processed: 2,
    analysis_units_total: 10,
    retrieved_source_count: 2,
    collection_chunk_count: 10,
    collection_document_count: 5,
    retrieval_latency_ms: 0,
    latency_ms: 20,
  },
};

describe("chat performance controls", () => {
  it("explains controls and defaults to fast chat without launching a review", async () => {
    render(<ChatClient />);
    expect(
      await screen.findByRole("option", {
        name: "Auto: lookups + matching sets",
      }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Answer scope")).toHaveValue("auto");
    expect(screen.getByLabelText("Collection")).toHaveAttribute(
      "title",
      "All collections",
    );
    expect(screen.getByLabelText("Top k")).toHaveAttribute("max", "20");
    fireEvent.click(screen.getByText("How search works"));
    expect(
      screen.getByText(/“all” or “list” is not required/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/does not currently expose additional metadata filters/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Combines meaning-based vector search/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Several passages may come from one document/),
    ).toBeInTheDocument();
    expect(mockApi.chatQuery).not.toHaveBeenCalled();
  });

  it("restores an active review, stops polling when stopped, and offers resume", async () => {
    mockApi.chatActiveAnalyses.mockResolvedValue([pendingReview]);
    mockApi.chatAnalysis.mockResolvedValue(pendingReview);
    mockApi.chatAnalysisControl
      .mockResolvedValueOnce({
        ...pendingReview,
        answer: "Review stopped.",
        metadata: { ...pendingReview.metadata, analysis_status: "cancelled" },
      })
      .mockResolvedValueOnce(pendingReview);
    render(<ChatClient />);
    fireEvent.click(await screen.findByRole("button", { name: "Stop review" }));
    expect(await screen.findByText("Review stopped.")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Stop review" }),
    ).not.toBeInTheDocument();
    expect(mockApi.chatAnalysisControl).toHaveBeenCalledWith(
      "review-1",
      "cancel",
    );
    fireEvent.click(screen.getByRole("button", { name: "Resume review" }));
    expect(
      await screen.findByRole("button", { name: "Stop review" }),
    ).toBeInTheDocument();
    expect(mockApi.chatAnalysisControl).toHaveBeenCalledWith(
      "review-1",
      "resume",
    );
    expect(mockApi.chatQuery).not.toHaveBeenCalled();
  });

  it("keeps a saved-reference reply when the shared review is stopped", async () => {
    // A reference reply carries the same analysis_id but is not a review.
    const referenceReply = {
      ...pendingReview,
      id: 92,
      answer: 'Found 2 saved source passages for "Atlas".',
      inventory: [],
      metadata: {
        ...pendingReview.metadata,
        answer_mode: "review_references",
        analysis_status: undefined,
      },
    };
    mockApi.chatActiveAnalyses.mockResolvedValue([pendingReview]);
    mockApi.chatAnalysis.mockResolvedValue(pendingReview);
    mockApi.chatQuery.mockResolvedValue(referenceReply);
    mockApi.chatAnalysisControl.mockResolvedValue({
      ...pendingReview,
      answer: "Review stopped.",
      metadata: { ...pendingReview.metadata, analysis_status: "cancelled" },
    });
    render(<ChatClient />);
    await screen.findByRole("button", { name: "Stop review" });
    fireEvent.change(
      screen.getByPlaceholderText("Ask a question about your documents..."),
      { target: { value: 'What references contain "Atlas"?' } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(
      await screen.findByText('Found 2 saved source passages for "Atlas".'),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Stop review" }));
    expect(await screen.findByText("Review stopped.")).toBeInTheDocument();
    // Stopping the review must not overwrite the reference reply.
    expect(
      screen.getByText('Found 2 saved source passages for "Atlas".'),
    ).toBeInTheDocument();
  });

  it("marks reused answers clearly", async () => {
    mockApi.chatQuery.mockResolvedValue({
      ...pendingReview,
      answer: "Saved answer [1].",
      metadata: {
        ...pendingReview.metadata,
        answer_mode: "generated",
        answer_cached: true,
        analysis_id: undefined,
        analysis_status: undefined,
      },
    });
    render(<ChatClient />);
    fireEvent.change(
      screen.getByPlaceholderText("Ask a question about your documents..."),
      { target: { value: "Explain deployment." } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByText("cached answer")).toBeInTheDocument();
    expect(
      screen.getByText(/Reused a saved local-model answer/),
    ).toBeInTheDocument();
  });
});

describe("chat inventory preview", () => {
  it.each([3, 50, 51, 75])(
    "shows up to 50 results out of %i with a text download",
    async (count) => {
      mockApi.chatQuery.mockResolvedValue({
        ...pendingReview,
        answer: "Review finished.",
        inventory: Array.from({ length: count }, (_, index) => ({
          name: `Result ${index + 1}`,
          source_number: 1,
          evidence: "Source text",
        })),
        metadata: { ...pendingReview.metadata, analysis_status: "complete" },
      });
      render(<ChatClient />);
      fireEvent.change(
        screen.getByPlaceholderText("Ask a question about your documents..."),
        { target: { value: "Who supplies us?" } },
      );
      fireEvent.click(screen.getByRole("button", { name: "Send" }));
      const preview = await screen.findByRole("region", {
        name: "Extracted results",
      });
      expect(within(preview).getAllByRole("listitem")).toHaveLength(
        Math.min(count, 50),
      );
      expect(
        within(preview).getByRole("button", {
          name: "Download full list (.txt)",
        }),
      ).toBeInTheDocument();
      expect(
        within(preview).queryByText("Result 51 [1]"),
      ).not.toBeInTheDocument();
      if (count > 50)
        expect(
          within(preview).getByText(
            `Showing the first 50 of ${count} results. Download the text file for the full extracted list.`,
          ),
        ).toBeInTheDocument();
    },
  );
});

it("previews actual merchant names while review is incomplete and retains them after stopping", async () => {
  const running = {
    ...pendingReview,
    answer:
      "Matches appear after each completed batch. Results are incomplete while the review is running.",
    inventory: ["Walgreens", "Amtrak", "IN-N-OUT Burger"].map((name) => ({
      name,
    })),
    metadata: {
      ...pendingReview.metadata,
      analysis_status: "running",
      analysis_units_processed: 4,
      analysis_units_total: 2565,
      analysis_batch_elapsed_seconds: 10,
    },
  };
  mockApi.chatActiveAnalyses.mockResolvedValue([running]);
  mockApi.chatAnalysis.mockResolvedValue(running);
  mockApi.chatAnalysisControl.mockResolvedValue({
    ...running,
    answer:
      "Review stopped. Results below cover only the processed text. Resume to continue.",
    metadata: { ...running.metadata, analysis_status: "cancelled" },
  });
  render(<ChatClient />);
  const region = await screen.findByRole("region", {
    name: "Extracted results",
  });
  for (const name of ["Walgreens", "Amtrak", "IN-N-OUT Burger"])
    expect(within(region).getByText(name)).toBeInTheDocument();
  // Evidence is not inlined, so nothing is fetched until a result is expanded.
  expect(mockApi.chatAnalysisReferences).not.toHaveBeenCalled();
  expect(within(region).queryByText(/Result ?0*1/)).not.toBeInTheDocument();
  expect(
    screen.queryByText(
      /Review status:|Saved progress through|Reviews every stored/,
    ),
  ).not.toBeInTheDocument();
  expect(
    within(region).getByRole("button", {
      name: "Download results so far (.txt)",
    }),
  ).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Stop review" }));
  await screen.findByRole("button", { name: "Resume review" });
  expect(screen.getByText("Stopped")).toBeInTheDocument();
  expect(within(region).getByText("Walgreens")).toBeInTheDocument();
  expect(
    screen.getByRole("progressbar", { name: "Text segments processed" }),
  ).toHaveAttribute("value", "4");
});
