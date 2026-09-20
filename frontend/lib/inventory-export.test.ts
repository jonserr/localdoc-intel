import { describe, expect, it } from "vitest";
import {
  INVENTORY_PREVIEW_LIMIT,
  inventoryFilename,
  inventoryText,
} from "./inventory-export";
import type { ChatResponse } from "@/types/api";

const response: ChatResponse = {
  id: 1,
  answer: "Processed 100 of 110 chunks. Ten chunks could not be reviewed.",
  citations: [
    {
      source_number: 1,
      document: "Contract.txt",
      document_id: 1,
      chunk_id: 1,
      page: 2,
      start_line: null,
      end_line: null,
      score: 0,
      text_preview: "$125.00",
      retrieval_source: "collection_review",
    },
  ],
  // The list API returns names only. Evidence loads on demand.
  inventory: Array.from({ length: 75 }, (_, i) => ({
    name: `Result ${i + 1}`,
  })),
  metadata: {
    retrieval_mode: "hybrid",
    retrieval_top_k: 5,
    embedding_model: "embed",
    llm_model: "llm",
    answer_mode: "collection_analysis",
    generation_error: "",
    retrieval_latency_ms: 0,
    latency_ms: 10,
    analysis_status: "partial",
    analysis_id: "11111111-1111-4111-8111-111111111111",
    analysis_collection: "Demo",
    analysis_units_processed: 100,
    analysis_units_total: 110,
    collection_document_count: 12,
    collection_chunk_count: 110,
  },
};

describe("inventory text export", () => {
  it("exports every result beyond the preview, not just the previewed 50", () => {
    const text = inventoryText("Which values appear?", response);
    const results = text.split("Results:\n")[1].trim().split("\n");
    expect(results).toHaveLength(75);
    expect(results).toHaveLength(response.inventory!.length);
    expect(results.length).toBeGreaterThan(INVENTORY_PREVIEW_LIMIT);
    expect(results[0]).toBe("Result 1");
    expect(results[74]).toBe("Result 75");
  });

  it("records coverage and status so a partial list is never read as complete", () => {
    const text = inventoryText("Which values appear?", response);
    expect(text).toContain("Review status: partial");
    expect(text).toContain("Collection: Demo");
    expect(text).toContain("Review ID: 11111111-1111-4111-8111-111111111111");
    expect(text).toContain(
      "Coverage: 100 of 110 text segments; 12 documents, 110 stored chunks.",
    );
    expect(text).toContain(response.answer);
  });

  it("says how many extracted values the filter left unjudged", () => {
    const text = inventoryText("Which values appear?", {
      ...response,
      metadata: {
        ...response.metadata,
        analysis_filter_total: 45,
        analysis_filter_pending: 5,
      },
    });
    expect(text).toContain(
      "Filter: 5 extracted values are not listed because the filter did not judge them.",
    );
    expect(inventoryText("Which values appear?", response)).not.toContain(
      "Filter:",
    );
  });

  it("records the merged spellings so the file is not lossy", () => {
    const text = inventoryText("Which values appear?", {
      ...response,
      inventory: [
        {
          name: "MADISON GmbH",
          variants: ["MADISON GmbH", "MADISON Hotel GmbH"],
        },
        { name: "Beacon" },
      ],
    });
    const results = text.split("Results:\n")[1].trim().split("\n");
    expect(results).toEqual([
      "MADISON GmbH (also: MADISON Hotel GmbH)",
      "Beacon",
    ]);
  });

  it("omits source excerpts, which are fetched per result instead", () => {
    const text = inventoryText("Which values appear?", response);
    expect(text).not.toContain("Sources and matching excerpts");
    expect(text).not.toContain("Contract.txt");
    expect(text).not.toContain("$125.00");
  });

  it("keeps one result per line when a value contains newlines", () => {
    const text = inventoryText("Which values appear?", {
      ...response,
      inventory: [{ name: "Acme\nCorp" }, { name: "Beta" }],
    });
    const results = text.split("Results:\n")[1].trim().split("\n");
    expect(results).toEqual(["Acme Corp", "Beta"]);
  });

  it("names files using the question and unique review identity", () => {
    const first = inventoryFilename("Who supplies us?", response);
    expect(first).toBe(
      "localdoc-who-supplies-us-11111111-1111-4111-8111-111111111111.txt",
    );
    expect(inventoryFilename("What dates appear?", response)).not.toBe(first);
    expect(
      inventoryFilename("Who supplies us?", {
        ...response,
        metadata: {
          ...response.metadata,
          analysis_id: "22222222-2222-4222-8222-222222222222",
        },
      }),
    ).not.toBe(first);
    expect(inventoryFilename("../../危険\n?", response)).toMatch(
      /^localdoc-results-[a-z0-9-]+\.txt$/,
    );
  });
});
