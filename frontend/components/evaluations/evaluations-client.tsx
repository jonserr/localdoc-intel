"use client";

import { AlertCircle, BarChart3, FileQuestion, Play } from "lucide-react";
import { FormEvent, useEffect, useMemo, useRef, useState } from "react";

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
import { Input } from "@/components/ui/input";
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
  formatPercent,
  formatScore,
} from "@/lib/format";
import type { EvaluationRun, RetrievalMode } from "@/types/api";

// Metric cards before any run exists: nothing was measured
const NO_RUNS = "n/a (no runs)";

function strategyLabel(run: EvaluationRun) {
  const mode = run.retrieval_mode || "";
  const strategy = run.retrieval_strategy || "";
  if (mode && strategy && mode !== strategy) {
    return `${mode} → ${strategy}`;
  }
  if (strategy) {
    return strategy;
  }
  return mode ? `${mode} (strategy not recorded)` : "Not recorded";
}

export function EvaluationsClient() {
  const [selectedRunId, setSelectedRunId] = useState<number | null>(null);
  const [inspectCount, setInspectCount] = useState(0);
  const summaryRef = useRef<HTMLHeadingElement>(null);
  const [runs, setRuns] = useState<EvaluationRun[]>([]);
  const [name, setName] = useState("Manual evaluation");
  const [mode, setMode] = useState<RetrievalMode>("hybrid");
  const [topK, setTopK] = useState(5);
  const [rerank, setRerank] = useState(true);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    async function loadEvaluations() {
      try {
        setLoading(true);
        setError(null);
        const data = await api.evaluations();
        if (active) {
          setRuns(data);
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

    void loadEvaluations();
    return () => {
      active = false;
    };
  }, []);

  // Brings the updated summary into view after an explicit inspection
  useEffect(() => {
    if (!inspectCount) {
      return;
    }
    const heading = summaryRef.current;
    heading?.scrollIntoView?.({ block: "start", behavior: "smooth" });
    heading?.focus({ preventScroll: true });
  }, [inspectCount]);

  function inspectRun(runId: number) {
    setSelectedRunId(runId);
    setInspectCount((count) => count + 1);
  }

  async function runEvaluation(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      setSubmitting(true);
      setError(null);
      const run = await api.runEvaluation({
        name,
        mode,
        top_k: topK,
        rerank,
      });
      setRuns((current) => [run, ...current]);
      setSelectedRunId(run.id);
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setSubmitting(false);
    }
  }

  const latest = runs.find((run) => run.id === selectedRunId) ?? runs[0];
  const metrics = useMemo(() => {
    const hasLabeled = Boolean(
      latest && (latest.labeled_question_count ?? 0) > 0,
    );
    const hasCoverage = Boolean(
      latest && (latest.coverage_question_count ?? 0) > 0,
    );
    return [
      [
        "Recall@k",
        latest
          ? hasLabeled
            ? formatPercent(latest.recall_at_k)
            : "n/a (open questions)"
          : NO_RUNS,
      ],
      [
        "MRR",
        latest
          ? hasLabeled
            ? formatScore(latest.mean_reciprocal_rank)
            : "n/a (open questions)"
          : NO_RUNS,
      ],
      [
        "Expected-term coverage",
        latest
          ? hasCoverage
            ? formatPercent(latest.expected_term_coverage)
            : "n/a (open questions)"
          : NO_RUNS,
      ],
      [
        "Groundedness (lexical proxy)",
        latest
          ? hasCoverage
            ? formatPercent(latest.groundedness_score)
            : "n/a (open questions)"
          : NO_RUNS,
      ],
      [
        "Judge score",
        latest && latest.judged_answer_count > 0
          ? formatPercent(latest.answer_quality_score)
          : "No score",
      ],
      [
        "Unrelated-query rejection rate",
        !latest
          ? NO_RUNS
          : (latest.no_results_question_count ?? 0) > 0 &&
              latest.no_results_precision != null
            ? `${formatPercent(latest.no_results_precision)} (n=${latest.no_results_question_count})`
            : "n/a (no labeled negatives)",
      ],
      ["Latency", latest ? formatLatency(latest.average_latency_ms) : NO_RUNS],
    ];
  }, [latest]);

  return (
    <>
      <section className="flex flex-col justify-between gap-4 md:flex-row md:items-end">
        <div className="flex max-w-3xl flex-col gap-2">
          <h1 className="text-3xl font-semibold">Evaluations</h1>
          <p className="text-muted-foreground">
            Run the local retrieval and answer-quality harness against the
            editable questions in <code>data/demo_questions.json</code>.
          </p>
        </div>
      </section>

      <div className="grid gap-6 xl:grid-cols-[1fr_0.85fr]">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <SafeIcon icon={Play} />
              Run evaluation
            </CardTitle>
            <CardDescription>
              Uses the real backend evaluation endpoint and the configured local
              judge model.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form
              className="flex flex-wrap items-center gap-3"
              onSubmit={runEvaluation}
            >
              <Input
                className="min-w-44 flex-1"
                value={name}
                onChange={(event) => setName(event.target.value)}
                aria-label="Evaluation run name"
              />
              <select
                className="h-10 rounded-md border bg-background px-3 text-sm"
                value={mode}
                onChange={(event) =>
                  setMode(event.target.value as RetrievalMode)
                }
                aria-label="Evaluation retrieval mode"
              >
                <option value="hybrid">hybrid</option>
                <option value="vector">vector</option>
                <option value="metadata-filtered">metadata-filtered</option>
              </select>
              <Input
                className="w-24"
                type="number"
                min={1}
                max={20}
                value={topK}
                onChange={(event) => setTopK(Number(event.target.value))}
                aria-label="Evaluation top k"
              />
              <label className="flex h-10 items-center gap-2 rounded-md border px-3 text-sm">
                <input
                  type="checkbox"
                  checked={rerank}
                  onChange={(event) => setRerank(event.target.checked)}
                />
                Rerank
              </label>
              <Button disabled={submitting}>
                {submitting ? "Running..." : "Run"}
              </Button>
            </form>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <SafeIcon icon={FileQuestion} />
              Question source
            </CardTitle>
            <CardDescription>
              Edit the JSON file locally to test your own documents.
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3 text-sm">
            <code className="rounded-md bg-muted px-3 py-2">
              data/demo_questions.json
            </code>
            <p className="leading-6 text-muted-foreground">
              Questions can be open-ended for OCR demos or include expected
              document/term fields for regression metrics.
            </p>
          </CardContent>
        </Card>
      </div>

      {error ? (
        <Card className="border-destructive/30 bg-destructive/5">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <SafeIcon icon={AlertCircle} />
              Evaluation request failed
            </CardTitle>
            <CardDescription>{error}</CardDescription>
          </CardHeader>
        </Card>
      ) : null}

      {latest ? (
        <h2
          ref={summaryRef}
          tabIndex={-1}
          className="scroll-mt-36 text-sm text-muted-foreground outline-none [overflow-wrap:anywhere] lg:scroll-mt-24"
        >
          Showing metrics for{" "}
          <span className="font-medium text-foreground">{latest.name}</span>
        </h2>
      ) : null}

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {metrics.map(([label, value]) => (
          <Card key={label}>
            <CardHeader>
              <CardDescription>{label}</CardDescription>
              <CardTitle className="text-2xl">
                {loading ? <Skeleton className="h-8 w-16" /> : value}
              </CardTitle>
            </CardHeader>
          </Card>
        ))}
      </section>

      {latest ? (
        <Card>
          <CardHeader>
            <CardTitle className="[overflow-wrap:anywhere]">
              Run details: {latest.name}
            </CardTitle>
            <CardDescription>
              Metrics above describe this run. The unrelated-query rejection
              rate measures how often questions labeled unrelated returned no
              passages; n is the number of those questions.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {latest.fallback_reason ? (
              <p className="rounded-md border p-3 text-sm [overflow-wrap:anywhere]">
                Retrieval fallback: {latest.fallback_reason}
              </p>
            ) : null}
            <details>
              <summary className="cursor-pointer text-sm font-medium text-primary">
                Reproducibility details
              </summary>
              <dl className="mt-4 grid gap-4 sm:grid-cols-2">
                {[
                  ["Requested mode", latest.retrieval_mode],
                  ["Actual strategy", latest.retrieval_strategy],
                  ["Top k", latest.top_k],
                  ["Vector relevance floor", latest.config?.vector_min_score],
                  [
                    "Vector search",
                    latest.config?.vector_search_enabled == null
                      ? undefined
                      : latest.config.vector_search_enabled
                        ? "Enabled"
                        : "Disabled",
                  ],
                  [
                    "Answer generation",
                    latest.config?.answer_generation_enabled == null
                      ? undefined
                      : latest.config.answer_generation_enabled
                        ? "Enabled"
                        : "Disabled",
                  ],
                  [
                    "Evaluation scope",
                    latest.config?.retrieval_only == null
                      ? undefined
                      : latest.config.retrieval_only
                        ? "Retrieval only"
                        : "Retrieval, generation and judging requested",
                  ],
                  [
                    "Reranking",
                    latest.rerank == null
                      ? undefined
                      : latest.rerank
                        ? "Enabled"
                        : "Disabled",
                  ],
                  ["Embedding model", latest.embedding_model],
                  ["Answer model", latest.llm_model],
                  ["Judge model", latest.answer_judge_model],
                  ["Corpus documents", latest.corpus_document_count],
                  ["Corpus hash (source bytes)", latest.corpus_hash],
                  ["Corpus chunks", latest.corpus_chunk_count],
                  ["Chunk hash (retrieval units)", latest.chunk_hash],
                  ["Question-set hash", latest.question_set_hash],
                  ["Question-set path", latest.question_set_path],
                  ["Revision", latest.revision],
                ].map(([label, value]) => (
                  <div key={label} className="min-w-0">
                    <dt className="text-xs text-muted-foreground">{label}</dt>
                    <dd className="mt-1 break-all font-mono text-sm">
                      {value === undefined || value === null || value === ""
                        ? "Not recorded"
                        : value}
                    </dd>
                  </div>
                ))}
              </dl>
            </details>
          </CardContent>
        </Card>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <SafeIcon icon={BarChart3} />
            Evaluation history
          </CardTitle>
          <CardDescription>
            {loading
              ? "Loading evaluation runs..."
              : `${runs.length} evaluation runs recorded.`}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {loading ? (
            <Skeleton className="h-44 w-full" />
          ) : runs.length ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Run</TableHead>
                  <TableHead>Questions</TableHead>
                  <TableHead>Strategy</TableHead>
                  <TableHead>Unrelated rejected</TableHead>
                  <TableHead>Recall</TableHead>
                  <TableHead>MRR</TableHead>
                  <TableHead>Term coverage</TableHead>
                  <TableHead>Grounded (lexical)</TableHead>
                  <TableHead>Judge</TableHead>
                  <TableHead>Judge model</TableHead>
                  <TableHead>Latency</TableHead>
                  <TableHead>Created</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {runs.map((run) => (
                  <TableRow key={run.id}>
                    <TableCell className="font-medium">
                      <div className="flex flex-col items-start gap-2">
                        <span>{run.name}</span>
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          className="whitespace-nowrap"
                          aria-label={`Inspect ${run.name}`}
                          aria-pressed={latest?.id === run.id}
                          onClick={() => inspectRun(run.id)}
                        >
                          Inspect run
                        </Button>
                      </div>
                    </TableCell>
                    <TableCell>{run.question_count}</TableCell>
                    <TableCell title={run.fallback_reason || undefined}>
                      {strategyLabel(run)}
                    </TableCell>
                    <TableCell>
                      {(run.no_results_question_count ?? 0) > 0 &&
                      run.no_results_precision != null
                        ? `${formatPercent(run.no_results_precision)} (n=${run.no_results_question_count})`
                        : "n/a"}
                    </TableCell>
                    <TableCell>
                      {(run.labeled_question_count ?? 0) > 0
                        ? formatPercent(run.recall_at_k)
                        : "n/a"}
                    </TableCell>
                    <TableCell>
                      {(run.labeled_question_count ?? 0) > 0
                        ? formatScore(run.mean_reciprocal_rank)
                        : "n/a"}
                    </TableCell>
                    <TableCell>
                      {(run.coverage_question_count ?? 0) > 0
                        ? formatPercent(run.expected_term_coverage)
                        : "n/a"}
                    </TableCell>
                    <TableCell>
                      {(run.coverage_question_count ?? 0) > 0
                        ? formatPercent(run.groundedness_score)
                        : "n/a"}
                    </TableCell>
                    <TableCell>
                      {run.judged_answer_count > 0
                        ? `${formatPercent(run.answer_quality_score)} (${run.judged_answer_count})`
                        : "No score"}
                    </TableCell>
                    <TableCell>
                      {run.answer_judge_model || "Not recorded"}
                    </TableCell>
                    <TableCell>
                      {formatLatency(run.average_latency_ms)}
                    </TableCell>
                    <TableCell>{formatDate(run.created_at)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <EmptyState
              icon={BarChart3}
              title="No evaluation runs yet"
              description="Run an evaluation after ingesting documents. The backend will use data/demo_questions.json."
            />
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Per-question details</CardTitle>
          <CardDescription>
            The backend currently persists run-level metrics only.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <p className="text-sm leading-6 text-muted-foreground">
            Per-question answers, retrieved documents, and rationales are
            printed by the management command and used during scoring, but they
            are not exposed by the current API response. This UI intentionally
            avoids showing fabricated rows.
          </p>
        </CardContent>
      </Card>
    </>
  );
}
