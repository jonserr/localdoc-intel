"use client";

import { AlertCircle, BarChart3, FileQuestion, Play } from "lucide-react";
import { FormEvent, useEffect, useMemo, useState } from "react";

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

export function EvaluationsClient() {
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
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setSubmitting(false);
    }
  }

  const latest = runs[0];
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
          : "0%",
      ],
      [
        "MRR",
        latest
          ? hasLabeled
            ? formatScore(latest.mean_reciprocal_rank)
            : "n/a (open questions)"
          : "0.00",
      ],
      [
        "Citation coverage",
        latest
          ? hasCoverage
            ? formatPercent(latest.citation_coverage)
            : "n/a (open questions)"
          : "0%",
      ],
      [
        "Groundedness",
        latest
          ? hasCoverage
            ? formatPercent(latest.groundedness_score)
            : "n/a (open questions)"
          : "0%",
      ],
      [
        "Judge score",
        latest && latest.judged_answer_count > 0
          ? formatPercent(latest.answer_quality_score)
          : "No score",
      ],
      ["Latency", latest ? formatLatency(latest.average_latency_ms) : "0 ms"],
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

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-6">
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
                  <TableHead>Recall</TableHead>
                  <TableHead>MRR</TableHead>
                  <TableHead>Coverage</TableHead>
                  <TableHead>Grounded</TableHead>
                  <TableHead>Judge</TableHead>
                  <TableHead>Judge model</TableHead>
                  <TableHead>Latency</TableHead>
                  <TableHead>Created</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {runs.map((run) => (
                  <TableRow key={run.id}>
                    <TableCell className="font-medium">{run.name}</TableCell>
                    <TableCell>{run.question_count}</TableCell>
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
                        ? formatPercent(run.citation_coverage)
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
                      {run.answer_judge_model || "Unavailable"}
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
