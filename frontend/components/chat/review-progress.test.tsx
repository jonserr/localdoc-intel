import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { ChatResponse } from "@/types/api";
import { ReviewProgress } from "./review-progress";

const metadata: ChatResponse["metadata"] = {
  retrieval_mode: "hybrid",
  retrieval_top_k: 5,
  embedding_model: "embed",
  llm_model: "llm",
  answer_mode: "collection_analysis",
  generation_error: "",
  retrieval_latency_ms: 0,
  latency_ms: 40000,
  analysis_status: "running",
  analysis_units_processed: 4,
  analysis_units_total: 2565,
  analysis_batch_elapsed_seconds: 17,
  collection_document_count: 1158,
  collection_chunk_count: 2565,
};

describe("review progress", () => {
  it("shows precise completed progress, explains the current batch and preserves stopped progress", () => {
    const { rerender } = render(<ReviewProgress metadata={metadata} />);
    const bar = screen.getByRole("progressbar", {
      name: "Text segments processed",
    });
    expect(bar).toHaveAttribute("value", "4");
    expect(bar).toHaveAttribute("max", "2565");
    expect(bar).toHaveAttribute(
      "aria-valuetext",
      "4 of 2,565 text segments (0.16%)",
    );
    expect(screen.getAllByText(/4 of 2,565 text segments/)).toHaveLength(1);
    expect(
      screen.getByText(/Reading the current batch \(17s\)/),
    ).toBeInTheDocument();
    rerender(
      <ReviewProgress
        metadata={{ ...metadata, analysis_units_processed: 9 }}
      />,
    );
    expect(bar).toHaveAttribute("value", "9");
    expect(bar).toHaveAttribute(
      "aria-valuetext",
      "9 of 2,565 text segments (0.35%)",
    );
    rerender(
      <ReviewProgress
        metadata={{
          ...metadata,
          analysis_units_processed: 9,
          analysis_status: "cancelled",
          analysis_batch_elapsed_seconds: null,
        }}
      />,
    );
    expect(screen.getByText("Stopped")).toBeInTheDocument();
    expect(bar).toHaveAttribute("value", "9");
    expect(
      screen.queryByText(/Reading the current batch/),
    ).not.toBeInTheDocument();
  });
});
