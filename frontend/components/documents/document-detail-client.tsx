"use client";

import {
  AlertCircle,
  FileText,
  Hash,
  Info,
  Layers,
  RefreshCw,
} from "lucide-react";
import { useEffect, useState } from "react";

import { EmptyState } from "@/components/empty-state";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { SafeIcon } from "@/components/ui/safe-icon";
import { Skeleton } from "@/components/ui/skeleton";
import { api, getErrorMessage } from "@/lib/api";
import { formatBytes, formatDate, lineRange } from "@/lib/format";
import type { DocumentChunk, DocumentRecord } from "@/types/api";

function metadataValue(value: unknown) {
  if (value === null || value === undefined || value === "") {
    return "Not available";
  }
  if (typeof value === "boolean") {
    return value ? "yes" : "no";
  }
  if (typeof value === "object") {
    return JSON.stringify(value);
  }
  return String(value);
}

export function DocumentDetailClient({ id }: { id: string }) {
  const [document, setDocument] = useState<DocumentRecord | null>(null);
  const [chunks, setChunks] = useState<DocumentChunk[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshIndex, setRefreshIndex] = useState(0);

  useEffect(() => {
    let active = true;

    async function loadDocument() {
      try {
        setLoading(true);
        setError(null);
        const [documentData, chunkData] = await Promise.all([
          api.document(id),
          api.documentChunks(id),
        ]);
        if (active) {
          setDocument(documentData);
          setChunks(chunkData);
        }
      } catch (err) {
        if (active) {
          setError(getErrorMessage(err));
        }
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    }

    void loadDocument();
    return () => {
      active = false;
    };
  }, [id, refreshIndex]);

  if (error) {
    return (
      <Card className="border-destructive/30 bg-destructive/5">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <SafeIcon icon={AlertCircle} />
            Could not load document
          </CardTitle>
          <CardDescription>{error}</CardDescription>
        </CardHeader>
      </Card>
    );
  }

  const metadata = document?.metadata ?? {};
  const summary: [string, string | undefined][] = [
    ["Collection", document?.collection.name],
    ["File type", document ? `.${document.file_type}` : undefined],
    ["Chunks", document?.chunk_count.toString()],
    ["Size", document ? formatBytes(document.byte_size) : undefined],
    ["Status", document?.status],
    ["Indexed", formatDate(document?.last_indexed_at)],
  ];
  const parserRows: [string, unknown][] = [
    ["Parser", metadata.parser],
    ["Content type", metadata.content_type],
    ["OCR", metadata.ocr],
    ["Page count", metadata.page_count],
    ["Chunker", metadata.chunker],
    ["Stored path", metadata.stored_path],
    ["Source path", document?.source_path],
  ];

  return (
    <>
      <section className="flex flex-col justify-between gap-4 md:flex-row md:items-end">
        <div className="flex min-w-0 flex-col gap-2">
          <h1 className="truncate text-3xl font-semibold">
            {loading ? "Loading document" : document?.title}
          </h1>
          <p className="text-muted-foreground">
            Extracted text, chunk ranges, parser metadata, and ingestion state.
          </p>
        </div>
        <Button
          variant="outline"
          onClick={() => setRefreshIndex((value) => value + 1)}
          disabled={loading}
        >
          <SafeIcon icon={RefreshCw} />
          Refresh
        </Button>
      </section>

      {document?.error_message ? (
        <Card className="border-destructive/30 bg-destructive/5">
          <CardHeader>
            <CardTitle>Ingestion error</CardTitle>
            <CardDescription>{document.error_message}</CardDescription>
          </CardHeader>
        </Card>
      ) : null}

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-6">
        {summary.map(([label, value]) => (
          <Card key={label}>
            <CardHeader>
              <CardDescription>{label}</CardDescription>
              <CardTitle className="text-base">
                {loading ? <Skeleton className="h-6 w-24" /> : value}
              </CardTitle>
            </CardHeader>
          </Card>
        ))}
      </section>

      <section className="grid gap-6 xl:grid-cols-[0.85fr_1.15fr]">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <SafeIcon icon={Info} />
              Source metadata
            </CardTitle>
            <CardDescription>
              Parser and provenance fields returned by the backend.
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3 text-sm">
            {loading ? (
              <Skeleton className="h-48 w-full" />
            ) : (
              parserRows.map(([label, value]) => (
                <div
                  key={label}
                  className="grid gap-1 border-b pb-3 last:border-b-0"
                >
                  <span className="text-xs font-medium text-muted-foreground">
                    {label}
                  </span>
                  <span className="break-all">{metadataValue(value)}</span>
                </div>
              ))
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <SafeIcon icon={Layers} />
              Indexed chunks
            </CardTitle>
            <CardDescription>
              Full extracted chunk text with page, line, byte, and token
              metadata.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            {loading ? (
              <Skeleton className="h-44 w-full" />
            ) : chunks.length ? (
              chunks.map((chunk) => (
                <article key={chunk.id} className="rounded-md border p-4">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge variant="secondary">
                        <SafeIcon icon={Hash} />
                        chunk {chunk.chunk_index}
                      </Badge>
                      <Badge variant="outline">
                        {lineRange(
                          chunk.start_line,
                          chunk.end_line,
                          chunk.page,
                        )}
                      </Badge>
                      <Badge variant="muted">{chunk.token_count} tokens</Badge>
                    </div>
                    <span className="text-xs text-muted-foreground">
                      bytes {chunk.byte_start ?? "?"}-{chunk.byte_end ?? "?"}
                    </span>
                  </div>
                  <p className="mt-4 whitespace-pre-wrap text-sm leading-6 text-muted-foreground">
                    {chunk.text ||
                      chunk.text_preview ||
                      "No text extracted for this chunk."}
                  </p>
                </article>
              ))
            ) : (
              <EmptyState
                icon={FileText}
                title="No chunks available"
                description="The document exists, but no extracted chunks were returned by the backend."
              />
            )}
          </CardContent>
        </Card>
      </section>
    </>
  );
}
