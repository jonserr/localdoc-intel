import type { ChatResponse } from "@/types/api";

export function ReviewProgress({
  metadata,
}: {
  metadata: ChatResponse["metadata"];
}) {
  const processed = metadata.analysis_units_processed ?? 0;
  const total = metadata.analysis_units_total ?? 0;
  const percentage = total ? Math.min(100, (processed / total) * 100) : 0;
  const state = metadata.analysis_status ?? "queued";
  const labels = {
    queued: "Waiting for worker",
    running: "Reviewing",
    cancelled: "Stopped",
    failed: "Failed",
    complete: "Complete",
    partial: "Incomplete",
  };
  const progress = `${processed.toLocaleString()} of ${total.toLocaleString()} text segments (${percentage.toFixed(2)}%)`;
  // Filtering is a second pass over extracted values, so it has its own count.
  const filterTotal = metadata.analysis_filter_total ?? 0;
  const filterPending = metadata.analysis_filter_pending ?? 0;
  return (
    <section
      aria-label="Collection review progress"
      className="grid gap-2 text-xs text-muted-foreground"
    >
      <p aria-live="polite">
        <span className="font-medium text-foreground">{labels[state]}</span> ·{" "}
        {progress}
      </p>
      <progress
        className="h-2 w-full accent-primary"
        aria-label="Text segments processed"
        aria-valuetext={progress}
        value={processed}
        max={total || 1}
      />
      <p>
        Scope:{" "}
        {metadata.collection_document_count?.toLocaleString() ?? "unknown"}{" "}
        documents ·{" "}
        {metadata.collection_chunk_count?.toLocaleString() ?? "unknown"} stored
        chunks
        {metadata.analysis_cached_units
          ? ` · ${metadata.analysis_cached_units.toLocaleString()} segments reused from cache`
          : ""}
        {metadata.analysis_cached ? " · Saved review" : ""}
      </p>
      {filterTotal > 0 && filterPending > 0 ? (
        <p>
          Filter: {(filterTotal - filterPending).toLocaleString()} of{" "}
          {filterTotal.toLocaleString()} extracted values judged ·{" "}
          {filterPending.toLocaleString()} not listed until judged
        </p>
      ) : null}
      {state === "running" ? (
        <p className="flex items-center gap-2">
          <span
            aria-hidden="true"
            className="h-2 w-2 animate-pulse rounded-full bg-primary"
          />
          Reading the current batch
          {metadata.analysis_batch_elapsed_seconds != null
            ? ` (${metadata.analysis_batch_elapsed_seconds}s)`
            : ""}
          . The bar advances after it finishes.
        </p>
      ) : null}
    </section>
  );
}
