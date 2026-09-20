import type { ChatResponse } from "@/types/api";

export const INVENTORY_PREVIEW_LIMIT = 50;

export function inventoryText(
  question: string,
  response: ChatResponse,
): string {
  const meta = response.metadata;
  return [
    "LocalDoc Intel — extracted results",
    `Question: ${question}`,
    `Review status: ${meta.analysis_status ?? "unknown"}`,
    `Collection: ${meta.analysis_collection || "All collections"}`,
    `Review ID: ${meta.analysis_id ?? "unknown"}`,
    `Coverage: ${meta.analysis_units_processed ?? "unknown"} of ${meta.analysis_units_total ?? "unknown"} text segments; ${meta.collection_document_count ?? "unknown"} documents, ${meta.collection_chunk_count ?? "unknown"} stored chunks.`,
    // Undecided candidates are not results, so say how many were left out.
    ...(meta.analysis_filter_pending
      ? [
          `Filter: ${meta.analysis_filter_pending} extracted values are not listed because the filter did not judge them.`,
        ]
      : []),
    response.answer,
    "",
    "Results:",
    ...(response.inventory ?? []).map((entry) => {
      const name = entry.name.replace(/[\r\n]+/g, " ");
      const merged = (entry.variants ?? []).filter((value) => value !== name);
      return merged.length
        ? `${name} (also: ${merged.join("; ").replace(/[\r\n]+/g, " ")})`
        : name;
    }),
    "",
  ].join("\n");
}

export function inventoryFilename(
  question: string,
  response: ChatResponse,
): string {
  const slug =
    question
      .normalize("NFKD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-|-$/g, "")
      .slice(0, 60) || "results";
  const id = (response.metadata.analysis_id ?? String(response.id)).replace(
    /[^a-zA-Z0-9-]/g,
    "",
  );
  return `localdoc-${slug}-${id}.txt`;
}

export function downloadInventory(question: string, response: ChatResponse) {
  const url = URL.createObjectURL(
    new Blob([inventoryText(question, response)], {
      type: "text/plain;charset=utf-8",
    }),
  );
  const link = document.createElement("a");
  link.href = url;
  link.download = inventoryFilename(question, response);
  document.body.appendChild(link);
  link.click();
  link.remove();
  // Allow the browser to consume the URL before releasing its memory.
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
