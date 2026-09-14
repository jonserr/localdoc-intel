"use client";

import { useState } from "react";
import { api, getErrorMessage } from "@/lib/api";
import type { ChatResponse } from "@/types/api";

export function ResultSources({
  reviewId,
  value,
}: {
  reviewId: string;
  value: string;
}) {
  const [response, setResponse] = useState<ChatResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  async function load() {
    setLoading(true);
    try {
      setResponse(await api.chatAnalysisReferences(reviewId, value));
      setError("");
    } catch (error) {
      setError(getErrorMessage(error));
    } finally {
      setLoading(false);
    }
  }
  return (
    <details
      className="text-xs text-muted-foreground"
      onToggle={(event) => {
        if (event.currentTarget.open && !response && !loading) void load();
      }}
    >
      <summary className="cursor-pointer">Show sources for {value}</summary>
      {loading ? <p role="status">Loading saved sources…</p> : null}
      {error ? <p role="alert">{error}</p> : null}
      {response ? (
        <div className="mt-2 grid gap-2">
          <p>{response.answer}</p>
          {response.citations.map((source) => (
            <p key={source.chunk_id}>
              <a
                className="underline"
                href={`/documents/${source.document_id}`}
              >
                {source.document}
                {source.page ? ` (page ${source.page})` : ""}
              </a>
              : {source.text_preview}
            </p>
          ))}
        </div>
      ) : null}
    </details>
  );
}
