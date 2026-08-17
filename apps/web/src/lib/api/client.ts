// ---------------------------------------------------------------------------
// 30ai API Client
// ---------------------------------------------------------------------------
// Thin typed wrapper around `fetch` that talks to the FastAPI backend.
//
// Usage:
//   import { api } from "@/lib/api/client";
//   const docs = await api.getDocuments();
// ---------------------------------------------------------------------------

import type {
  Organization,
  User,
  Document,
  DocumentDetail,
  DocumentSearchResult,
  ProcessingJob,
  UploadUrlResponse,
  DownloadDocumentResponse,
  ProcessDocumentResponse,
  DeleteDocumentResponse,
  HealthCheckResponse,
  RootResponse,
} from "@/lib/api/types";

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

function getBaseUrl(): string {
  // NEXT_PUBLIC_API_URL is set in docker-compose or .env.local
  return process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
}

// ---------------------------------------------------------------------------
// Error handling
// ---------------------------------------------------------------------------

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
    public readonly body: unknown = null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function handleResponse<T>(response: Response): Promise<T | undefined> {
  if (!response.ok) {
    let body: unknown = null;
    try {
      body = await response.json();
    } catch {
      // ignore parse failures
    }
    const message =
      typeof body === "object" && body !== null && "detail" in body
        ? String((body as Record<string, unknown>).detail)
        : response.statusText ||
          `Request failed with status ${response.status}`;
    throw new ApiError(response.status, message, body);
  }

  // 204 No Content — nothing to parse
  if (response.status === 204) {
    return undefined;
  }

  return response.json() as Promise<T>;
}

// ---------------------------------------------------------------------------
// Core request helper
// ---------------------------------------------------------------------------

export interface RequestOptions {
  /** Additional headers to merge. */
  headers?: Record<string, string>;
  /** AbortSignal for cancellation. */
  signal?: AbortSignal;
  /** Override cache strategy (default: "no-store" for API calls). */
  cache?: RequestCache;
  /** Next.js revalidation tag for fetch cache. */
  next?: { tags?: string[]; revalidate?: number };
}

async function request<T>(
  path: string,
  options: RequestInit & RequestOptions = {},
): Promise<T | undefined> {
  const url = `${getBaseUrl()}${path}`;

  const { headers: extraHeaders, next, ...fetchOptions } = options;

  const response = await fetch(url, {
    ...fetchOptions,
    credentials: "include", // forward cookies if the API ever switches to cookie auth
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
      ...extraHeaders,
    },
    ...(next ? { next } : {}),
  });

  return handleResponse<T>(response);
}

// ---------------------------------------------------------------------------
// Convenience shorthands
// ---------------------------------------------------------------------------

async function get<T>(
  path: string,
  opts?: RequestOptions,
): Promise<T | undefined> {
  return request<T>(path, { ...opts, method: "GET" });
}

async function post<T>(
  path: string,
  body?: unknown,
  opts?: RequestOptions,
): Promise<T | undefined> {
  return request<T>(path, {
    ...opts,
    method: "POST",
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
}

async function del<T>(
  path: string,
  opts?: RequestOptions,
): Promise<T | undefined> {
  return request<T>(path, { ...opts, method: "DELETE" });
}

// ---------------------------------------------------------------------------
// API — typed functions for every backend endpoint
// ---------------------------------------------------------------------------

export const api = {
  // -----------------------------------------------------------------------
  // Root / Health
  // -----------------------------------------------------------------------

  /** GET / — welcome message. */
  getRoot(opts?: RequestOptions): Promise<RootResponse | undefined> {
    return get("/", opts);
  },

  /** GET /health — health check. */
  getHealth(opts?: RequestOptions): Promise<HealthCheckResponse | undefined> {
    return get("/health", opts);
  },

  // -----------------------------------------------------------------------
  // Organizations
  // -----------------------------------------------------------------------

  /** GET /api/organizations — list all organisations. */
  getOrganizations(opts?: RequestOptions): Promise<Organization[] | undefined> {
    return get("/api/organizations", opts);
  },

  /** GET /api/organizations/{id} — fetch a single organisation. */
  getOrganization(
    organizationId: string,
    opts?: RequestOptions,
  ): Promise<Organization | undefined> {
    return get(
      `/api/organizations/${encodeURIComponent(organizationId)}`,
      opts,
    );
  },

  // -----------------------------------------------------------------------
  // Users
  // -----------------------------------------------------------------------

  /** GET /api/users — list all users. */
  getUsers(opts?: RequestOptions): Promise<User[] | undefined> {
    return get("/api/users", opts);
  },

  // -----------------------------------------------------------------------
  // Documents
  // -----------------------------------------------------------------------

  /** GET /api/documents — list all documents. */
  getDocuments(opts?: RequestOptions): Promise<Document[] | undefined> {
    return get("/api/documents", opts);
  },

  /**
   * GET /api/documents/{documentId}
   * Fetch a single document's metadata, LLM summary, and processed
   * markdown content in one request.
   */
  getDocument(
    documentId: string,
    opts?: RequestOptions,
  ): Promise<DocumentDetail | undefined> {
    return get(`/api/documents/${encodeURIComponent(documentId)}`, opts);
  },

  /**
   * GET /api/documents/search?query=...
   * Semantic search over document content.
   */
  searchDocuments(
    query: string,
    opts?: RequestOptions,
  ): Promise<DocumentSearchResult[] | undefined> {
    const q = encodeURIComponent(query);
    return get(`/api/documents/search?query=${q}`, opts);
  },

  /**
   * GET /api/documents/upload-url/{filePath}
   * Get a presigned S3/R2 URL for uploading a file.
   */
  getUploadUrl(
    filePath: string,
    params: {
      organizationId: string;
      userId: string;
      contentType: string;
    },
    opts?: RequestOptions,
  ): Promise<UploadUrlResponse | undefined> {
    const qs = new URLSearchParams({
      organization_id: params.organizationId,
      user_id: params.userId,
      content_type: params.contentType,
    });
    return get(
      `/api/documents/upload-url/${encodeURIComponent(filePath)}?${qs.toString()}`,
      opts,
    );
  },

  /**
   * POST /api/documents/{jobId}/process
   * Trigger asynchronous document processing via Celery.
   */
  processDocument(
    jobId: string,
    opts?: RequestOptions,
  ): Promise<ProcessDocumentResponse | undefined> {
    return post(
      `/api/documents/${encodeURIComponent(jobId)}/process`,
      undefined,
      opts,
    );
  },

  /**
   * DELETE /api/documents/{documentId}
   * Delete a document and all associated artefacts.
   */
  deleteDocument(
    documentId: string,
    opts?: RequestOptions,
  ): Promise<DeleteDocumentResponse | undefined> {
    return del(`/api/documents/${encodeURIComponent(documentId)}`, opts);
  },

  /**
   * GET /api/documents/{documentId}/download
   * Get a time-limited presigned URL for downloading a document's
   * original file directly from object storage.
   */
  downloadDocument(
    documentId: string,
    opts?: RequestOptions,
  ): Promise<DownloadDocumentResponse | undefined> {
    return get(
      `/api/documents/${encodeURIComponent(documentId)}/download`,
      opts,
    );
  },

  // -----------------------------------------------------------------------
  // Processing Jobs
  // -----------------------------------------------------------------------

  /** GET /api/processing-jobs — list all processing jobs. */
  getProcessingJobs(
    opts?: RequestOptions,
  ): Promise<ProcessingJob[] | undefined> {
    return get("/api/processing-jobs", opts);
  },

  /** GET /api/processing-jobs/{jobId} — fetch a single processing job. */
  getProcessingJob(
    jobId: string,
    opts?: RequestOptions,
  ): Promise<ProcessingJob | undefined> {
    return get(`/api/processing-jobs/${encodeURIComponent(jobId)}`, opts);
  },
};

// ---------------------------------------------------------------------------
// Re-export convenience request helpers for advanced usage
// ---------------------------------------------------------------------------
export { get, post, del };
