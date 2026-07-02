import { render, screen } from "@testing-library/react";
import React from "react";
import { describe, expect, it } from "vitest";

import { CitationCard } from "@/components/citation-card";

describe("CitationCard", () => {
  it("renders document evidence", () => {
    render(
      <CitationCard
        document="guide.md"
        range="Lines 1-4"
        score="0.91"
        text="Validate the deployment before release."
      />,
    );

    expect(screen.getByText("guide.md")).toBeInTheDocument();
    expect(screen.getByText("Lines 1-4")).toBeInTheDocument();
    expect(screen.getByText("score 0.91")).toBeInTheDocument();
  });
});
