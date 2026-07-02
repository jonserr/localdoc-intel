"use client";

import { useCallback, useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api, getErrorMessage } from "@/lib/api";
import type { ServiceStatus, SystemStatusResponse } from "@/types/api";

function StatusDot({ ok }: { ok: boolean }) {
  return (
    <span
      aria-hidden
      className={`inline-block h-2.5 w-2.5 rounded-full ${ok ? "bg-emerald-500" : "bg-red-500"}`}
    />
  );
}

function serviceDetail(name: string, service: ServiceStatus): string {
  if (!service.available) {
    return "unreachable";
  }
  if (name === "ollama") {
    const models = [
      service.embedding_model_pulled ? null : "embedding model not pulled",
      service.llm_model_pulled ? null : "LLM not pulled",
    ].filter(Boolean);
    return models.length ? models.join(", ") : "models ready";
  }
  if (name === "qdrant") {
    return service.target_collection_exists
      ? `collection ${service.target_collection}`
      : "collection not created yet";
  }
  return "connected";
}

function serviceModelBadges(name: string, service: ServiceStatus) {
  if (name !== "ollama") {
    return null;
  }
  return (
    <div className="mt-2 flex flex-wrap gap-2">
      <Badge variant={service.embedding_model_pulled ? "secondary" : "outline"}>
        embeddings: {service.embedding_model_pulled ? "pulled" : "missing"}
      </Badge>
      <Badge variant={service.llm_model_pulled ? "secondary" : "outline"}>
        answer/judge: {service.llm_model_pulled ? "pulled" : "missing"}
      </Badge>
    </div>
  );
}

export function SystemStatusCard() {
  const [status, setStatus] = useState<SystemStatusResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchStatus = useCallback(() => {
    return api
      .status()
      .then((data) => {
        setStatus(data);
        setError(null);
      })
      .catch((err) => setError(getErrorMessage(err)))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    void fetchStatus();
  }, [fetchStatus]);

  function refresh() {
    setLoading(true);
    void fetchStatus();
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-4 space-y-0">
        <div className="flex flex-col gap-1.5">
          <CardTitle>Service status</CardTitle>
          <CardDescription>
            Local services powering ingestion, retrieval, and generation.
          </CardDescription>
        </div>
        <div className="flex items-center gap-2">
          {status ? (
            <Badge
              variant={status.status === "ok" ? "secondary" : "default"}
              className={status.status === "ok" ? "" : "bg-red-500 text-white"}
            >
              {status.status}
            </Badge>
          ) : null}
          <Button
            variant="outline"
            size="sm"
            onClick={refresh}
            disabled={loading}
          >
            Refresh
          </Button>
        </div>
      </CardHeader>
      <CardContent className="grid gap-3 text-sm">
        {loading && !status ? (
          <>
            <Skeleton className="h-5 w-full" />
            <Skeleton className="h-5 w-full" />
            <Skeleton className="h-5 w-full" />
            <Skeleton className="h-5 w-full" />
          </>
        ) : null}
        {error ? <p className="text-destructive">{error}</p> : null}
        {status
          ? Object.entries(status.services).map(([name, service]) => (
              <div
                key={name}
                className="border-b pb-3 last:border-b-0 last:pb-0"
              >
                <div className="flex items-center justify-between gap-4">
                  <span className="flex items-center gap-2 capitalize">
                    <StatusDot ok={service.available} />
                    {name}
                  </span>
                  <span className="text-right text-muted-foreground">
                    {serviceDetail(name, service)}
                  </span>
                </div>
                {service.error ? (
                  <p className="mt-2 text-xs text-destructive">
                    {service.error}
                  </p>
                ) : null}
                {serviceModelBadges(name, service)}
              </div>
            ))
          : null}
        {status ? (
          <div className="flex flex-wrap gap-2 pt-1">
            {Object.entries(status.features).map(([feature, enabled]) => (
              <Badge key={feature} variant={enabled ? "secondary" : "outline"}>
                {feature.replaceAll("_", " ")}: {enabled ? "on" : "off"}
              </Badge>
            ))}
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
