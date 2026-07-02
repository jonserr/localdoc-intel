import type {
  ChatHistoryItem,
  ChatQueryRequest,
  ChatResponse,
  Collection,
  DocumentChunk,
  DocumentRecord,
  EvaluationRunRequest,
  EvaluationRun,
  SettingsResponse,
  StatsResponse,
  SystemStatusResponse,
  UploadResponse,
} from "@/types/api";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_PROXY_BASE_URL ?? "/api/backend";

export class ApiError extends Error {
  status: number;
  body: unknown;

  constructor(message: string, status: number, body: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

type QueryValue = string | number | boolean | null | undefined;

function buildUrl(path: string, query?: Record<string, QueryValue>) {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  const url = new URL(
    `${API_BASE_URL}${normalizedPath}`,
    "http://localdoc.local",
  );

  Object.entries(query ?? {}).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") {
      url.searchParams.set(key, String(value));
    }
  });

  const pathname =
    url.pathname.length > 1 ? url.pathname.replace(/\/$/, "") : url.pathname;
  return `${pathname}${url.search}`;
}

async function parseResponse(response: Response) {
  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) {
    return response.json();
  }
  return response.text();
}

async function request<T>(
  path: string,
  init?: RequestInit,
  query?: Record<string, QueryValue>,
): Promise<T> {
  const response = await fetch(buildUrl(path, query), {
    ...init,
    headers: {
      ...(init?.body instanceof FormData
        ? {}
        : { "Content-Type": "application/json" }),
      ...init?.headers,
    },
  });
  const body = await parseResponse(response);

  if (!response.ok) {
    const message = typeof body === "string" ? body : response.statusText;
    throw new ApiError(message || "API request failed", response.status, body);
  }

  return body as T;
}

export function getErrorMessage(error: unknown) {
  if (error instanceof ApiError) {
    if (typeof error.body === "string") {
      return error.body;
    }
    if (error.body && typeof error.body === "object") {
      return Object.entries(error.body)
        .map(
          ([key, value]) =>
            `${key}: ${Array.isArray(value) ? value.join(", ") : String(value)}`,
        )
        .join("; ");
    }
    return `${error.status}: ${error.message}`;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "Unexpected error";
}

export const api = {
  stats: () => request<StatsResponse>("/stats/"),
  status: () => request<SystemStatusResponse>("/status/"),
  settings: () => request<SettingsResponse>("/settings/"),
  collections: () => request<Collection[]>("/collections/"),
  documents: (query?: {
    search?: string;
    collection?: string;
    file_type?: string;
    status?: string;
  }) => request<DocumentRecord[]>("/documents/", undefined, query),
  document: (id: number | string) =>
    request<DocumentRecord>(`/documents/${id}/`),
  chunks: (query?: {
    document_id?: number | string;
    collection?: string;
    search?: string;
  }) => request<DocumentChunk[]>("/chunks/", undefined, query),
  documentChunks: (id: number | string) =>
    request<DocumentChunk[]>(`/documents/${id}/chunks/`),
  uploadDocuments: (formData: FormData) =>
    request<UploadResponse>("/documents/upload/", {
      method: "POST",
      body: formData,
    }),
  chatQuery: (payload: ChatQueryRequest) =>
    request<ChatResponse>("/chat/query/", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  chatHistory: (query?: { collection?: string; retrieval_mode?: string }) =>
    request<ChatHistoryItem[]>("/chat/history/", undefined, query),
  evaluations: () => request<EvaluationRun[]>("/evaluations/"),
  runEvaluation: (payload: EvaluationRunRequest) =>
    request<EvaluationRun>("/evaluations/run/", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
};
