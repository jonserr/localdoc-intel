import { Badge } from "@/components/ui/badge";
import type { VectorIndexingState } from "@/types/api";

export const vectorIndexLabels: Record<VectorIndexingState, string> = {
  not_requested: "Not requested",
  disabled: "Disabled",
  queued: "Queued",
  running: "Running",
  succeeded: "Succeeded",
  failed: "Failed",
};

export function VectorIndexBadge({
  state = "not_requested",
  count,
}: {
  state?: VectorIndexingState;
  count?: number;
}) {
  const label = vectorIndexLabels[state];
  return (
    <Badge
      variant={state === "succeeded" ? "secondary" : "outline"}
      className={
        state === "failed"
          ? "border-destructive/40 text-destructive"
          : undefined
      }
      aria-label={`Vector index: ${label}${count === undefined ? "" : ` (${count})`}`}
    >
      {label}
      {count === undefined ? "" : `: ${count}`}
    </Badge>
  );
}
