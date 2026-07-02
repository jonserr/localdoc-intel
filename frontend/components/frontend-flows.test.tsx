import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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
  citation_coverage: 0.8,
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
        embedding_model: "embed",
        llm_model: "llm",
        answer_mode: "generated",
        generation_error: "",
        retrieval_latency_ms: 30,
        latency_ms: 80,
        rerank: true,
      },
    });

    render(<ChatClient />);

    fireEvent.change(
      screen.getByPlaceholderText(
        "What dates, totals, vendors, or source files are visible?",
      ),
      { target: { value: "What is the total?" } },
    );
    fireEvent.click(screen.getByRole("button", { name: /send/i }));

    expect(
      await screen.findByText("The total is 12.34 [1]"),
    ).toBeInTheDocument();
    expect(screen.getByText("Total 12.34")).toBeInTheDocument();
    expect(screen.getByText("score 0.92")).toBeInTheDocument();
  });

  it("renders backend chat errors", async () => {
    mockApi.chatQuery.mockRejectedValue(new Error("Ollama unavailable"));

    render(<ChatClient />);

    fireEvent.change(
      screen.getByPlaceholderText(
        "What dates, totals, vendors, or source files are visible?",
      ),
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

    expect(await screen.findByText("Receipt eval")).toBeInTheDocument();
    expect(
      screen.getAllByText("data/demo_questions.json")[0],
    ).toBeInTheDocument();
    expect(screen.getAllByText("75%")[0]).toBeInTheDocument();
    expect(screen.getByText("local-judge")).toBeInTheDocument();
  });
});
