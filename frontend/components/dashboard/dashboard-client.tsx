"use client";

import {
  BarChart3,
  Database,
  FileSearch,
  FileText,
  MessageSquareText,
  Play,
  Terminal,
  Upload,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { EmptyState } from "@/components/empty-state";
import { SystemStatusCard } from "@/components/system-status-card";
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { api, getErrorMessage } from "@/lib/api";
import {
  formatDate,
  formatLatency,
  formatNumber,
  formatPercent,
} from "@/lib/format";
import type {
  ChatHistoryItem,
  DocumentRecord,
  EvaluationRun,
  StatsResponse,
} from "@/types/api";

type DashboardState = {
  stats: StatsResponse | null;
  documents: DocumentRecord[];
  queries: ChatHistoryItem[];
  evaluations: EvaluationRun[];
};

const nextSteps = [
  {
    title: "Download demo receipts",
    description:
      "Populate data/demo_intake/ with the full Kaggle receipts PDF dataset.",
    command: "make demo-data",
    icon: Terminal,
  },
  {
    title: "Ingest local intake",
    description:
      "Parse, OCR, chunk, and index whatever supported files are in data/demo_intake/.",
    command: "make ingest-demo",
    icon: Upload,
  },
  {
    title: "Ask with citations",
    description:
      "Query indexed documents and inspect the retrieved evidence behind each answer.",
    href: "/chat",
    icon: MessageSquareText,
  },
  {
    title: "Run evaluation",
    description:
      "Score retrieval and answer quality with questions from data/demo_questions.json.",
    href: "/evaluations",
    icon: BarChart3,
  },
];

function statusVariant(status: string) {
  if (status === "indexed") return "secondary" as const;
  if (status === "failed") return "default" as const;
  return "muted" as const;
}

export function DashboardClient() {
  const [data, setData] = useState<DashboardState>({
    stats: null,
    documents: [],
    queries: [],
    evaluations: [],
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    async function loadDashboard() {
      try {
        setLoading(true);
        setError(null);
        const [stats, documents, queries, evaluations] = await Promise.all([
          api.stats(),
          api.documents(),
          api.chatHistory(),
          api.evaluations(),
        ]);
        if (active) {
          setData({
            stats,
            documents: documents.slice(0, 6),
            queries: queries.slice(0, 4),
            evaluations: evaluations.slice(0, 4),
          });
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

    void loadDashboard();
    return () => {
      active = false;
    };
  }, []);

  const latestEvaluation = data.evaluations[0];
  const cards = useMemo(
    () => [
      {
        label: "Documents",
        value: formatNumber(data.stats?.total_documents ?? 0),
        detail: `${formatNumber(data.stats?.documents_by_status.indexed ?? 0)} indexed`,
        icon: FileText,
      },
      {
        label: "Chunks",
        value: formatNumber(data.stats?.total_chunks ?? 0),
        detail: "retrievable passages",
        icon: FileSearch,
      },
      {
        label: "Chat queries",
        value: formatNumber(data.queries.length),
        detail: "recent conversations loaded",
        icon: MessageSquareText,
      },
      {
        label: "Evaluation runs",
        value: formatNumber(data.evaluations.length),
        detail: latestEvaluation
          ? `${formatPercent(latestEvaluation.answer_quality_score)} judge score`
          : "no runs yet",
        icon: BarChart3,
      },
    ],
    [data.evaluations, data.queries.length, data.stats, latestEvaluation],
  );

  return (
    <>
      <section className="flex flex-col justify-between gap-4 md:flex-row md:items-end">
        <div className="flex max-w-3xl flex-col gap-2">
          <h1 className="text-3xl font-semibold">Local document workspace</h1>
          <p className="text-muted-foreground">
            Intake local files, OCR receipts and scans, retrieve with hybrid
            search, and answer with visible citations from your private corpus.
          </p>
        </div>
        <div className="flex flex-wrap gap-3">
          <Button asChild>
            <Link href="/documents/upload">
              <SafeIcon icon={Upload} />
              Intake files
            </Link>
          </Button>
          <Button asChild variant="outline">
            <Link href="/chat">
              <SafeIcon icon={MessageSquareText} />
              Ask a question
            </Link>
          </Button>
        </div>
      </section>

      {error ? (
        <Card className="border-destructive/30 bg-destructive/5">
          <CardHeader>
            <CardTitle>Backend unavailable</CardTitle>
            <CardDescription>{error}</CardDescription>
          </CardHeader>
        </Card>
      ) : null}

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {cards.map((item) => {
          const Icon = item.icon;
          return (
            <Card key={item.label}>
              <CardHeader className="flex flex-row items-start justify-between space-y-0">
                <div>
                  <CardDescription>{item.label}</CardDescription>
                  <CardTitle className="mt-2 text-2xl">
                    {loading ? <Skeleton className="h-8 w-20" /> : item.value}
                  </CardTitle>
                </div>
                <div className="flex size-9 items-center justify-center rounded-md border bg-background text-muted-foreground">
                  <SafeIcon icon={Icon} />
                </div>
              </CardHeader>
              <CardContent>
                {loading ? (
                  <Skeleton className="h-4 w-32" />
                ) : (
                  <p className="text-sm text-muted-foreground">{item.detail}</p>
                )}
              </CardContent>
            </Card>
          );
        })}
      </section>

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {nextSteps.map((step) => {
          const Icon = step.icon;
          return (
            <Card key={step.title}>
              <CardHeader>
                <div className="flex items-start justify-between gap-3">
                  <div className="flex size-9 items-center justify-center rounded-md border bg-background text-muted-foreground">
                    <SafeIcon icon={Icon} />
                  </div>
                  {step.command ? (
                    <Badge variant="outline">terminal</Badge>
                  ) : null}
                </div>
                <CardTitle>{step.title}</CardTitle>
                <CardDescription>{step.description}</CardDescription>
              </CardHeader>
              <CardContent>
                {step.command ? (
                  <code className="block rounded-md bg-muted px-3 py-2 text-sm">
                    {step.command}
                  </code>
                ) : (
                  <Button asChild variant="outline" size="sm">
                    <Link href={step.href ?? "/"}>
                      <SafeIcon icon={Play} />
                      Open
                    </Link>
                  </Button>
                )}
              </CardContent>
            </Card>
          );
        })}
      </section>

      <section className="grid gap-6 xl:grid-cols-[1fr_0.9fr]">
        <SystemStatusCard />
        <Card>
          <CardHeader>
            <CardTitle>Latest ingestion</CardTitle>
            <CardDescription>
              Most recent document status and corpus composition.
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4 text-sm">
            <div className="flex items-center justify-between gap-4 border-b pb-3">
              <span className="text-muted-foreground">Status</span>
              {loading ? (
                <Skeleton className="h-5 w-20" />
              ) : (
                <Badge variant="secondary">
                  {data.stats?.latest_ingestion_status ?? "empty"}
                </Badge>
              )}
            </div>
            <div className="flex items-center justify-between gap-4 border-b pb-3">
              <span className="text-muted-foreground">Latest file</span>
              {loading ? (
                <Skeleton className="h-5 w-32" />
              ) : (
                <span className="max-w-[65%] truncate font-medium">
                  {data.stats?.latest_document?.title ?? "No documents indexed"}
                </span>
              )}
            </div>
            <div className="flex flex-wrap gap-2">
              {loading ? (
                <Skeleton className="h-8 w-full" />
              ) : Object.keys(data.stats?.documents_by_file_type ?? {})
                  .length ? (
                Object.entries(data.stats?.documents_by_file_type ?? {}).map(
                  ([type, count]) => (
                    <Badge key={type} variant="outline">
                      .{type}: {count}
                    </Badge>
                  ),
                )
              ) : (
                <span className="text-muted-foreground">
                  File-type summary appears after ingestion.
                </span>
              )}
            </div>
          </CardContent>
        </Card>
      </section>

      <section className="grid gap-6 xl:grid-cols-[1.35fr_1fr]">
        <Card>
          <CardHeader>
            <CardTitle>Recent documents</CardTitle>
            <CardDescription>
              Source files currently available to retrieval.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {loading ? (
              <Skeleton className="h-44 w-full" />
            ) : data.documents.length ? (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Name</TableHead>
                    <TableHead>Type</TableHead>
                    <TableHead>Chunks</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Indexed</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.documents.map((document) => (
                    <TableRow key={document.id}>
                      <TableCell className="font-medium">
                        <Link href={`/documents/${document.id}`}>
                          {document.title}
                        </Link>
                      </TableCell>
                      <TableCell>.{document.file_type}</TableCell>
                      <TableCell>{document.chunk_count}</TableCell>
                      <TableCell>
                        <Badge variant={statusVariant(document.status)}>
                          {document.status}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        {formatDate(document.last_indexed_at)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <EmptyState
                icon={Database}
                title="No documents indexed yet"
                description="Run make demo-data and make ingest-demo, or upload local files from the intake page."
              />
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Recent activity</CardTitle>
            <CardDescription>
              Latest chat and evaluation records.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            {loading ? (
              <Skeleton className="h-36 w-full" />
            ) : data.queries.length || data.evaluations.length ? (
              <>
                {data.queries.map((query) => (
                  <div
                    key={`query-${query.id}`}
                    className="rounded-md border p-3"
                  >
                    <p className="line-clamp-2 text-sm font-medium">
                      {query.question}
                    </p>
                    <div className="mt-3 flex flex-wrap gap-2 text-xs text-muted-foreground">
                      <Badge variant="outline">{query.retrieval_mode}</Badge>
                      <span>{query.citation_count} citations</span>
                      <span>{formatLatency(query.latency_ms)}</span>
                    </div>
                  </div>
                ))}
                {data.evaluations.map((run) => (
                  <div key={`eval-${run.id}`} className="rounded-md border p-3">
                    <p className="text-sm font-medium">{run.name}</p>
                    <div className="mt-3 flex flex-wrap gap-2 text-xs text-muted-foreground">
                      <Badge variant="outline">evaluation</Badge>
                      <span>{run.question_count} questions</span>
                      <span>{formatDate(run.created_at)}</span>
                    </div>
                  </div>
                ))}
              </>
            ) : (
              <EmptyState
                icon={MessageSquareText}
                title="No activity yet"
                description="Ask a question or run an evaluation after documents are indexed."
              />
            )}
          </CardContent>
        </Card>
      </section>
    </>
  );
}
