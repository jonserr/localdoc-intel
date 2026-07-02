"use client";

import { AlertCircle, Database, RefreshCw, Upload } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { EmptyState } from "@/components/empty-state";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { SafeIcon } from "@/components/ui/safe-icon";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { api, getErrorMessage } from "@/lib/api";
import { formatBytes, formatDate } from "@/lib/format";
import type { DocumentRecord, DocumentStatus } from "@/types/api";

type Filters = {
  search: string;
  collection: string;
  file_type: string;
  status: string;
};

const initialFilters: Filters = {
  search: "",
  collection: "",
  file_type: "",
  status: "",
};

function statusVariant(status: DocumentStatus) {
  if (status === "indexed") return "secondary" as const;
  if (status === "failed") return "default" as const;
  return "muted" as const;
}

export function DocumentsClient() {
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [filters, setFilters] = useState<Filters>(initialFilters);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshIndex, setRefreshIndex] = useState(0);

  useEffect(() => {
    let active = true;

    async function loadDocuments() {
      try {
        setLoading(true);
        setError(null);
        const data = await api.documents(filters);
        if (active) {
          setDocuments(data);
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

    void loadDocuments();
    return () => {
      active = false;
    };
  }, [filters, refreshIndex]);

  function updateFilter(key: keyof Filters, value: string) {
    setFilters((current) => ({ ...current, [key]: value }));
  }

  const hasFilters = Object.values(filters).some(Boolean);

  return (
    <>
      <section className="flex flex-col justify-between gap-4 md:flex-row md:items-end">
        <div className="flex flex-col gap-2">
          <h1 className="text-3xl font-semibold">Documents</h1>
          <p className="text-muted-foreground">
            Browse ingested files, parser metadata, indexing status, and source
            chunks used for RAG answers.
          </p>
        </div>
        <div className="flex flex-wrap gap-3">
          <Button
            variant="outline"
            onClick={() => setRefreshIndex((value) => value + 1)}
            disabled={loading}
          >
            <SafeIcon icon={RefreshCw} />
            Refresh
          </Button>
          <Button asChild>
            <Link href="/documents/upload">
              <SafeIcon icon={Upload} />
              Intake files
            </Link>
          </Button>
        </div>
      </section>

      <Card>
        <CardHeader>
          <CardTitle>Find documents</CardTitle>
          <CardDescription>
            Search by name or narrow by collection, file extension, and status.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-4">
          <Input
            value={filters.search}
            onChange={(event) => updateFilter("search", event.target.value)}
            placeholder="Search filename"
          />
          <Input
            value={filters.collection}
            onChange={(event) => updateFilter("collection", event.target.value)}
            placeholder="Collection"
          />
          <Input
            value={filters.file_type}
            onChange={(event) => updateFilter("file_type", event.target.value)}
            placeholder="File type, e.g. pdf"
          />
          <Input
            value={filters.status}
            onChange={(event) => updateFilter("status", event.target.value)}
            placeholder="Status, e.g. indexed"
          />
        </CardContent>
      </Card>

      {error ? (
        <Card className="border-destructive/30 bg-destructive/5">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <SafeIcon icon={AlertCircle} />
              Could not load documents
            </CardTitle>
            <CardDescription>{error}</CardDescription>
          </CardHeader>
        </Card>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle>Document library</CardTitle>
          <CardDescription>
            {loading
              ? "Loading documents..."
              : `${documents.length} files returned by the backend.`}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="grid gap-3">
              <Skeleton className="h-12 w-full" />
              <Skeleton className="h-12 w-full" />
              <Skeleton className="h-12 w-full" />
            </div>
          ) : documents.length ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>File</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Chunks</TableHead>
                  <TableHead>Size</TableHead>
                  <TableHead>Source</TableHead>
                  <TableHead>Updated</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {documents.map((document) => (
                  <TableRow key={document.id}>
                    <TableCell>
                      <div className="flex max-w-72 flex-col gap-1">
                        <Link
                          href={`/documents/${document.id}`}
                          className="font-medium text-primary"
                        >
                          {document.title}
                        </Link>
                        <span className="truncate text-xs text-muted-foreground">
                          {document.original_filename}
                        </span>
                        {document.error_message ? (
                          <span className="text-xs text-destructive">
                            {document.error_message}
                          </span>
                        ) : null}
                      </div>
                    </TableCell>
                    <TableCell>.{document.file_type}</TableCell>
                    <TableCell>
                      <Badge variant={statusVariant(document.status)}>
                        {document.status}
                      </Badge>
                    </TableCell>
                    <TableCell>{document.chunk_count}</TableCell>
                    <TableCell>{formatBytes(document.byte_size)}</TableCell>
                    <TableCell>
                      <span className="block max-w-64 truncate text-xs text-muted-foreground">
                        {document.source_path || "Stored upload"}
                      </span>
                    </TableCell>
                    <TableCell>{formatDate(document.updated_at)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <EmptyState
              icon={hasFilters ? AlertCircle : Database}
              title={
                hasFilters
                  ? "No documents match the filters"
                  : "No documents indexed"
              }
              description={
                hasFilters
                  ? "Clear or adjust the filters to see more files."
                  : "Run make demo-data and make ingest-demo, or upload supported files from this UI."
              }
            />
          )}
        </CardContent>
      </Card>
    </>
  );
}
