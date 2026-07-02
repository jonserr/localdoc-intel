"use client";

import { CheckCircle2, FileUp, FolderInput, Terminal } from "lucide-react";
import Link from "next/link";
import { ChangeEvent, DragEvent, FormEvent, useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { SafeIcon } from "@/components/ui/safe-icon";
import { api, getErrorMessage } from "@/lib/api";
import { formatBytes } from "@/lib/format";
import type { UploadResponse } from "@/types/api";

const coreTypes = [
  ".pdf",
  ".png",
  ".jpg",
  ".jpeg",
  ".tif",
  ".tiff",
  ".txt",
  ".md",
  ".csv",
  ".tsv",
  ".json",
  ".jsonl",
  ".docx",
  ".xlsx",
];

const extendedTypes = [
  ".html",
  ".xml",
  ".yaml",
  ".rst",
  ".log",
  ".xlsm",
  ".ods",
  ".odt",
  ".pptx",
  ".eml",
  ".rtf",
  ".bmp",
  ".webp",
];

export function UploadClient() {
  const [collection, setCollection] = useState("Demo");
  const [files, setFiles] = useState<File[]>([]);
  const [dragActive, setDragActive] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [progressMessage, setProgressMessage] = useState(
    "Drop or choose files to prepare ingestion.",
  );
  const [response, setResponse] = useState<UploadResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const selectedFiles = useMemo(
    () =>
      files.length
        ? files
            .map((file) => `${file.name} (${formatBytes(file.size)})`)
            .join(", ")
        : "",
    [files],
  );

  function selectFiles(fileList: FileList | null) {
    const nextFiles = fileList ? Array.from(fileList) : [];
    setResponse(null);
    setError(null);
    setProgress(nextFiles.length ? 12 : 0);
    setProgressMessage(
      nextFiles.length
        ? `${nextFiles.length} file${nextFiles.length === 1 ? "" : "s"} ready for intake.`
        : "Drop or choose files to prepare ingestion.",
    );
    setFiles(nextFiles);
  }

  function handleDrop(event: DragEvent<HTMLLabelElement>) {
    event.preventDefault();
    setDragActive(false);
    selectFiles(event.dataTransfer.files);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!files.length) {
      setError("Choose at least one file to upload.");
      return;
    }

    const formData = new FormData();
    formData.set("collection", collection);
    files.forEach((file) => formData.append("files", file));

    let progressTimer: number | undefined;
    try {
      setUploading(true);
      setProgress(28);
      setProgressMessage("Uploading files to the backend...");
      setError(null);
      setResponse(null);
      progressTimer = window.setInterval(() => {
        setProgress((value) => Math.min(value + 4, 88));
        setProgressMessage("Backend is parsing, OCRing, chunking, and indexing...");
      }, 900);
      const result = await api.uploadDocuments(formData);
      if (progressTimer) {
        window.clearInterval(progressTimer);
      }
      setProgress(100);
      setProgressMessage(
        `Finished intake: ${result.documents.length} indexed, ${result.errors.length} failed.`,
      );
      setResponse(result);
    } catch (err) {
      if (progressTimer) {
        window.clearInterval(progressTimer);
      }
      setProgress(0);
      setProgressMessage("Intake did not complete.");
      setError(getErrorMessage(err));
    } finally {
      setUploading(false);
    }
  }

  return (
    <>
      <section className="flex flex-col gap-2">
        <h1 className="text-3xl font-semibold">Intake and upload</h1>
        <p className="text-muted-foreground">
          Use the local intake folder for repeatable OCR/RAG demos, or upload
          files directly from the browser into the backend.
        </p>
      </section>

      <div className="grid gap-6 xl:grid-cols-[0.9fr_1.1fr]">
        <Card>
          <CardHeader>
            <div className="flex items-start justify-between gap-4">
              <div>
                <CardTitle className="flex items-center gap-2">
                  <SafeIcon icon={FolderInput} />
                  Local intake workflow
                </CardTitle>
                <CardDescription>
                  Best for the Kaggle receipt demo and arbitrary local files.
                </CardDescription>
              </div>
              <Badge variant="secondary">recommended</Badge>
            </div>
          </CardHeader>
          <CardContent className="grid gap-4">
            <div className="rounded-md border bg-background p-4">
              <p className="text-sm font-medium">
                1. Download default receipts
              </p>
              <code className="mt-2 block rounded-md bg-muted px-3 py-2 text-sm">
                make demo-data
              </code>
              <p className="mt-2 text-sm leading-6 text-muted-foreground">
                Downloads the full <code>jenswalter/receipts</code> Kaggle
                dataset through KaggleHub and copies all PDF files into{" "}
                <code>data/demo_intake/</code>.
              </p>
            </div>
            <div className="rounded-md border bg-background p-4">
              <p className="text-sm font-medium">2. Add or replace files</p>
              <p className="mt-2 text-sm leading-6 text-muted-foreground">
                Drop any supported local files into{" "}
                <code>data/demo_intake/</code>. The folder is ignored by Git and
                is never redistributed.
              </p>
            </div>
            <div className="rounded-md border bg-background p-4">
              <p className="text-sm font-medium">3. Ingest current intake</p>
              <code className="mt-2 block rounded-md bg-muted px-3 py-2 text-sm">
                make ingest-demo
              </code>
              <p className="mt-2 text-sm leading-6 text-muted-foreground">
                Recursively scans the folder, skips hidden/temp/empty files,
                OCRs scans and images, chunks text, and indexes retrieval
                evidence.
              </p>
            </div>
            <div className="rounded-md border bg-background p-4">
              <p className="text-sm font-medium">
                4. Edit evaluation questions
              </p>
              <code className="mt-2 block rounded-md bg-muted px-3 py-2 text-sm">
                data/demo_questions.json
              </code>
              <p className="mt-2 text-sm leading-6 text-muted-foreground">
                This file controls demo/evaluation questions for your current
                documents.
              </p>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <SafeIcon icon={FileUp} />
              Browser upload
            </CardTitle>
            <CardDescription>
              Uses the real backend upload endpoint for one-off files.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form className="flex flex-col gap-5" onSubmit={handleSubmit}>
              <label
                className={`flex min-h-56 cursor-pointer flex-col items-center justify-center gap-4 rounded-md border border-dashed p-8 text-center transition-colors ${
                  dragActive
                    ? "border-emerald-500 bg-emerald-500/10"
                    : "bg-muted/30 hover:bg-muted"
                }`}
                onDragEnter={() => setDragActive(true)}
                onDragLeave={() => setDragActive(false)}
                onDragOver={(event) => {
                  event.preventDefault();
                  setDragActive(true);
                }}
                onDrop={handleDrop}
              >
                <SafeIcon icon={FileUp} />
                <span className="text-base font-medium">
                  Drop files here or choose files
                </span>
                <span className="max-w-xl text-sm leading-6 text-muted-foreground">
                  {selectedFiles ||
                    "PDFs, images, text, Markdown, tables, JSON, Office XML files, HTML/XML/YAML, logs, email, and RTF are supported."}
                </span>
                <input
                  type="file"
                  multiple
                  aria-label="Choose files to upload"
                  className="sr-only"
                  onChange={(event: ChangeEvent<HTMLInputElement>) =>
                    selectFiles(event.target.files)
                  }
                />
              </label>
              <div className="grid gap-4 md:grid-cols-[1fr_auto]">
                <Input
                  value={collection}
                  onChange={(event) => setCollection(event.target.value)}
                  placeholder="Collection name"
                />
                <Button disabled={uploading}>
                  {uploading ? "Uploading..." : "Start upload"}
                </Button>
              </div>
              <div className="flex flex-col gap-3 rounded-md border p-4">
                <div className="flex items-center justify-between text-sm">
                  <span className="font-medium">Ingestion progress</span>
                  <span className="font-medium text-emerald-600">
                    {progress}%
                  </span>
                </div>
                <Progress value={progress} variant="success" className="h-3" />
                <p className="text-sm text-muted-foreground">
                  {response ? response.detail : progressMessage}
                </p>
                {response?.documents.length ? (
                  <div className="rounded-md bg-muted/50 p-3 text-sm">
                    <p className="flex items-center gap-2 font-medium">
                      <SafeIcon icon={CheckCircle2} />
                      Indexed documents
                    </p>
                    <ul className="mt-2 space-y-1 text-muted-foreground">
                      {response.documents.map((item) => (
                        <li key={item.document.id}>
                          {item.document.original_filename} -{" "}
                          {item.document.chunk_count} chunks -{" "}
                          {item.created ? "new" : "updated"}
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}
                {response?.errors.length ? (
                  <div className="rounded-md border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
                    <p className="font-medium">
                      Some files could not be ingested
                    </p>
                    <ul className="mt-2 space-y-1">
                      {response.errors.map((item) => (
                        <li key={`${item.filename ?? item.path}-${item.error}`}>
                          {item.filename ?? item.path}: {item.error}
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}
                {response ? (
                  <Button asChild variant="outline">
                    <Link href="/documents">View document library</Link>
                  </Button>
                ) : null}
                {error ? (
                  <p className="text-sm text-destructive">{error}</p>
                ) : null}
              </div>
            </form>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <SafeIcon icon={Terminal} />
            Supported formats
          </CardTitle>
          <CardDescription>
            Legacy .doc, .xls, and .ppt require LibreOffice and may be skipped
            if conversion is unavailable.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4 md:grid-cols-2">
          <div>
            <p className="mb-3 text-sm font-medium">Core formats</p>
            <div className="flex flex-wrap gap-2">
              {coreTypes.map((type) => (
                <Badge key={type} variant="outline">
                  {type}
                </Badge>
              ))}
            </div>
          </div>
          <div>
            <p className="mb-3 text-sm font-medium">
              Additional best-effort formats
            </p>
            <div className="flex flex-wrap gap-2">
              {extendedTypes.map((type) => (
                <Badge key={type} variant="muted">
                  {type}
                </Badge>
              ))}
            </div>
          </div>
        </CardContent>
      </Card>
    </>
  );
}
