"use client";

import { useEffect, useState } from "react";

import { SystemStatusCard } from "@/components/system-status-card";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api, getErrorMessage } from "@/lib/api";
import type { SettingsResponse } from "@/types/api";

export function SettingsClient() {
  const [settings, setSettings] = useState<SettingsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    api
      .settings()
      .then((data) => {
        if (active) {
          setSettings(data);
        }
      })
      .catch((err) => {
        if (active) {
          setError(getErrorMessage(err));
        }
      })
      .finally(() => {
        if (active) {
          setLoading(false);
        }
      });
    return () => {
      active = false;
    };
  }, []);

  const rows = [
    ["Ollama base URL", settings?.ollama_base_url],
    ["Embedding model", settings?.embedding_model],
    ["Answer model", settings?.llm_model],
    ["Judge model", settings?.eval_judge_model],
    ["Qdrant URL", settings?.qdrant_url],
    ["Redis URL", settings?.redis_url],
    ["Version", settings?.version],
  ];
  const runtimeRows = [
    ["Detected CPU", settings?.runtime?.cpu_count?.toString()],
    [
      "Detected RAM",
      settings?.runtime?.memory_mb
        ? `${settings.runtime.memory_mb.toLocaleString()} MB`
        : "Unknown",
    ],
    [
      "Ingestion workers",
      settings?.runtime?.active.ingestion_max_workers?.toString(),
    ],
    [
      "Celery concurrency",
      settings?.runtime?.active.celery_worker_concurrency?.toString(),
    ],
    ["OCR PDF DPI", settings?.runtime?.active.ocr_pdf_dpi?.toString()],
    [
      "OCR timeout",
      settings?.runtime?.active.ocr_timeout_seconds
        ? `${settings.runtime.active.ocr_timeout_seconds}s`
        : undefined,
    ],
  ];

  return (
    <>
      <section className="flex flex-col gap-2">
        <h1 className="text-3xl font-semibold">Settings</h1>
        <p className="text-muted-foreground">
          Inspect local model settings, service status, and privacy posture.
        </p>
      </section>

      {error ? (
        <Card>
          <CardHeader>
            <CardTitle>Could not load settings</CardTitle>
            <CardDescription>{error}</CardDescription>
          </CardHeader>
        </Card>
      ) : null}

      <SystemStatusCard />

      <div className="grid gap-6 xl:grid-cols-[1fr_0.8fr]">
        <Card>
          <CardHeader>
            <CardTitle>Local system</CardTitle>
            <CardDescription>
              These values are returned by the backend settings endpoint.
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4">
            {rows.map(([label, value]) => (
              <div
                key={label}
                className="flex items-center justify-between gap-4 border-b pb-3 text-sm last:border-b-0 last:pb-0"
              >
                <span className="text-muted-foreground">{label}</span>
                <span className="font-medium">
                  {loading ? <Skeleton className="h-4 w-28" /> : value}
                </span>
              </div>
            ))}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Runtime tuning</CardTitle>
            <CardDescription>
              Auto-detected defaults can be overridden in .env when needed.
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4">
            {runtimeRows.map(([label, value]) => (
              <div
                key={label}
                className="flex items-center justify-between gap-4 border-b pb-3 text-sm last:border-b-0 last:pb-0"
              >
                <span className="text-muted-foreground">{label}</span>
                <span className="font-medium">
                  {loading ? <Skeleton className="h-4 w-20" /> : value}
                </span>
              </div>
            ))}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Privacy note</CardTitle>
            <CardDescription>
              LocalDoc Intel is designed for private documents.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <p className="text-sm leading-6 text-muted-foreground">
              {loading ? "Loading privacy posture..." : settings?.privacy}
            </p>
            {settings ? (
              <div className="grid gap-2 text-sm">
                {Object.entries(settings.features).map(([feature, state]) => (
                  <div
                    key={feature}
                    className="flex items-center justify-between gap-4"
                  >
                    <span className="text-muted-foreground">
                      {feature.replaceAll("_", " ")}
                    </span>
                    <Badge
                      variant={
                        state === "enabled" || state === "available"
                          ? "secondary"
                          : "outline"
                      }
                    >
                      {state}
                    </Badge>
                  </div>
                ))}
              </div>
            ) : null}
          </CardContent>
        </Card>
      </div>
    </>
  );
}
