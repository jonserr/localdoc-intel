import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ChatResponse } from "@/types/api";

const mockApi = vi.hoisted(() => ({ chatAnalysisReferences: vi.fn() }));

vi.mock("@/lib/api", () => ({
  api: mockApi,
  getErrorMessage: (error: unknown) =>
    error instanceof Error ? error.message : String(error),
}));

import { ResultSources } from "@/components/chat/result-sources";

const REVIEW_ID = "11111111-1111-4111-8111-111111111111";

function referencesResponse(overrides: Partial<ChatResponse> = {}) {
  return {
    id: 7,
    answer: 'Found 2 saved source passages for "Amtrak".',
    citations: [
      {
        source_number: 1,
        document: "amtrak-20190510.pdf",
        document_id: 41,
        chunk_id: 101,
        page: 1,
        start_line: null,
        end_line: null,
        score: 0,
        text_preview: "Amtrak ticket, total $88.00",
        retrieval_source: "collection_review",
      },
      {
        source_number: 2,
        document: "travel-summary.txt",
        document_id: 42,
        chunk_id: 102,
        page: null,
        start_line: 3,
        end_line: 4,
        score: 0,
        text_preview: "Rail: Amtrak, booked 2019-05-10",
        retrieval_source: "collection_review",
      },
    ],
    inventory: [],
    metadata: {
      retrieval_mode: "hybrid" as const,
      retrieval_top_k: 5,
      embedding_model: "embed",
      llm_model: "llm",
      answer_mode: "review_references" as const,
      generation_error: "",
      retrieval_latency_ms: 0,
      latency_ms: 4,
      analysis_id: REVIEW_ID,
    },
    ...overrides,
  } as ChatResponse;
}

function expand() {
  const details = screen
    .getByText(/Show sources for/)
    .closest("details") as HTMLDetailsElement;
  details.open = true;
  fireEvent(details, new Event("toggle"));
  return details;
}

describe("lazy source loading", () => {
  beforeEach(() => {
    mockApi.chatAnalysisReferences.mockReset();
  });

  it("requests nothing until the result is expanded", () => {
    render(<ResultSources reviewId={REVIEW_ID} value="Amtrak" />);
    expect(screen.getByText("Show sources for Amtrak")).toBeInTheDocument();
    expect(mockApi.chatAnalysisReferences).not.toHaveBeenCalled();
  });

  it("shows a loading state, then the saved sources for that exact value", async () => {
    let resolve: (value: ChatResponse) => void = () => {};
    mockApi.chatAnalysisReferences.mockReturnValue(
      new Promise<ChatResponse>((r) => {
        resolve = r;
      }),
    );
    render(<ResultSources reviewId={REVIEW_ID} value="Amtrak" />);
    const details = expand();
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Loading saved sources",
    );
    resolve(referencesResponse());
    await waitFor(() =>
      expect(screen.queryByRole("status")).not.toBeInTheDocument(),
    );
    expect(mockApi.chatAnalysisReferences).toHaveBeenCalledWith(
      REVIEW_ID,
      "Amtrak",
    );
    expect(
      within(details).getByText('Found 2 saved source passages for "Amtrak".'),
    ).toBeInTheDocument();
    expect(
      within(details).getByRole("link", {
        name: "amtrak-20190510.pdf (page 1)",
      }),
    ).toHaveAttribute("href", "/documents/41");
    expect(
      within(details).getByText(/Amtrak ticket, total \$88\.00/),
    ).toBeInTheDocument();
    expect(
      within(details).getByText(/Rail: Amtrak, booked 2019-05-10/),
    ).toBeInTheDocument();
  });

  it("reports a failure instead of showing empty sources", async () => {
    mockApi.chatAnalysisReferences.mockRejectedValue(
      new Error("Review not found."),
    );
    render(<ResultSources reviewId={REVIEW_ID} value="Amtrak" />);
    expand();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Review not found.",
    );
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("states plainly when a value has no saved passages", async () => {
    mockApi.chatAnalysisReferences.mockResolvedValue(
      referencesResponse({
        answer: 'Found 0 saved source passages for "Amtrak".',
        citations: [],
      }),
    );
    render(<ResultSources reviewId={REVIEW_ID} value="Amtrak" />);
    const details = expand();
    expect(
      await within(details).findByText(
        'Found 0 saved source passages for "Amtrak".',
      ),
    ).toBeInTheDocument();
    expect(within(details).queryByRole("link")).not.toBeInTheDocument();
  });

  it("does not refetch when a loaded result is collapsed and reopened", async () => {
    mockApi.chatAnalysisReferences.mockResolvedValue(referencesResponse());
    render(<ResultSources reviewId={REVIEW_ID} value="Amtrak" />);
    const details = expand();
    await within(details).findByText(
      'Found 2 saved source passages for "Amtrak".',
    );
    expect(mockApi.chatAnalysisReferences).toHaveBeenCalledTimes(1);
    details.open = false;
    fireEvent(details, new Event("toggle"));
    details.open = true;
    fireEvent(details, new Event("toggle"));
    await waitFor(() =>
      expect(mockApi.chatAnalysisReferences).toHaveBeenCalledTimes(1),
    );
  });
});
