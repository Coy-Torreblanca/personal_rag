// ---------------------------------------------------------------------------
// 30ai Upload helpers
// ---------------------------------------------------------------------------
// Browser-side upload flow for sending a local file straight to R2 and
// automatically kicking off document processing:
//
//   1. Resolve an organization + user to own the upload (see
//      `resolveUploadContext`).
//   2. Ask the API for a time-limited presigned PUT URL
//      (`GET /api/documents/upload-url/{file_path}`).
//   3. PUT the file bytes directly to the presigned R2 URL — the file
//      never passes through our API server.
//   4. Trigger processing (`POST /api/documents/{job_id}/process`) as soon
//      as the upload completes, so the file is embedded and searchable
//      without any further user action.
//
// The API records a `Document` (status `UPLOADING`) and a pending
// `ProcessingJob` before the URL is handed out, so after a successful PUT
// the file is immediately visible to search. Steps 3 and 4 form one
// logical operation from the user's perspective: `uploadFileToR2` only
// resolves once the file is in R2 **and** processing has been dispatched
// (or the dispatch failure has been captured for the UI to surface).
// ---------------------------------------------------------------------------

import { api, ApiError } from "@/lib/api/client";
import type {
  ProcessDocumentResponse,
  UploadUrlResponse,
} from "@/lib/api/types";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Organization + user that own an upload (mirrors the API's query params). */
export interface UploadContext {
  organizationId: string;
  userId: string;
}

/** Live upload progress, reported via XMLHttpRequest. */
export interface UploadProgress {
  /** Bytes transferred so far. */
  loaded: number;
  /** Total bytes to transfer. */
  total: number;
  /** Percentage completed (0–100), rounded. */
  percent: number;
}

/** Outcome of the automatic processing-dispatch step. */
export interface ProcessOutcome {
  /** The API's `ProcessDocumentResponse` on success, else null. */
  response: ProcessDocumentResponse | null;
  /** Human-readable error if dispatch failed, else null. */
  error: string | null;
}

/** Combined result of an upload + automatic processing dispatch. */
export interface UploadResult {
  /** The API's `UploadUrlResponse` (includes the created `job_id`). */
  uploadUrl: UploadUrlResponse;
  /** Outcome of the automatic processing dispatch. */
  process: ProcessOutcome;
}

/** Options for `uploadFileToR2`. */
export interface UploadOptions {
  /** Optional callback receiving live upload progress. */
  onProgress?: (progress: UploadProgress) => void;
  /**
   * Whether to automatically trigger document processing once the file
   * is in R2. Defaults to `true`.
   */
  autoProcess?: boolean;
}

/** Convert an unknown thrown value into a human-readable message. */
export function toErrorMessage(err: unknown): string {
  return err instanceof Error ? err.message : "An unexpected error occurred";
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// ---------------------------------------------------------------------------
// Context resolution
// ---------------------------------------------------------------------------

// The upload URL endpoint requires `organization_id` and `user_id` query
// params, but the web app has no authentication yet. Both are resolved
// exclusively from `NEXT_PUBLIC_ORGANIZATION_ID` / `NEXT_PUBLIC_USER_ID`
// environment variables — they are required, so a missing variable fails
// fast with a clear error instead of silently picking an arbitrary org.
//
// The result is cached so repeated uploads don't re-fetch.
let cachedContext: UploadContext | null = null;

export async function resolveUploadContext(): Promise<UploadContext> {
  if (cachedContext) return cachedContext;

  const envOrganizationId = process.env.NEXT_PUBLIC_ORGANIZATION_ID;
  const envUserId = process.env.NEXT_PUBLIC_USER_ID;

  const organizationId: string | undefined = envOrganizationId;
  const userId: string | undefined = envUserId;

  // Both IDs are required — there is no API fallback while the web app
  // has no authentication yet.

  if (!organizationId || !userId) {
    throw new Error(
      "Could not resolve an organization and user for the upload. " +
        "Set NEXT_PUBLIC_ORGANIZATION_ID and NEXT_PUBLIC_USER_ID ",
    );
  }

  cachedContext = { organizationId, userId };
  return cachedContext;
}

// ---------------------------------------------------------------------------
// Processing dispatch
// ---------------------------------------------------------------------------

// How many times to attempt dispatching processing for transient failures
// (network errors / 5xx) before giving up.
const PROCESS_RETRY_ATTEMPTS = 3;

/**
 * Trigger document processing for an uploaded file and wait for the
 * dispatch to be accepted.
 *
 * The backend refuses to double-process a job (it must be `PENDING`), so
 * retrying is safe: if a previous attempt actually dispatched the Celery
 * task but its response was lost, the retry returns a 400 which we treat
 * as success (processing is already underway).
 *
 * @param jobId The `job_id` returned by the upload-url endpoint.
 * @returns A `ProcessOutcome` describing whether dispatch succeeded.
 */
export async function processUploadedDocument(
  jobId: string,
): Promise<ProcessOutcome> {
  let lastError: unknown = null;

  for (let attempt = 1; attempt <= PROCESS_RETRY_ATTEMPTS; attempt++) {
    try {
      const response = await api.processDocument(jobId);
      return { response: response ?? null, error: null };
    } catch (err) {
      // A 400 from the process endpoint means the job is no longer
      // `PENDING` — i.e. an earlier attempt already dispatched the task.
      // The only exception is the file-missing message, which is
      // practically impossible right after a successful PUT (R2 is
      // strongly consistent); it falls through to the retry path.
      if (err instanceof ApiError && err.status === 400) {
        const detail = String(err.message ?? "").toLowerCase();
        if (!detail.includes("not been uploaded")) {
          return { response: null, error: null };
        }
      }

      // Non-transient client errors (e.g. 404 job not found) will never
      // heal on retry — bail out immediately.
      if (err instanceof ApiError && err.status < 500) {
        return { response: null, error: toErrorMessage(err) };
      }

      lastError = err;
      if (attempt < PROCESS_RETRY_ATTEMPTS) {
        await sleep(500 * attempt); // linear backoff: 0.5s, 1s
      }
    }
  }

  return { response: null, error: toErrorMessage(lastError) };
}

// ---------------------------------------------------------------------------
// Upload
// ---------------------------------------------------------------------------

/** PUT the file body to a presigned R2 URL, reporting progress. */
function putFileToR2(
  url: string,
  contentType: string,
  file: File,
  onProgress?: (progress: UploadProgress) => void,
): Promise<void> {
  // XMLHttpRequest is used (rather than `fetch`) so upload progress can
  // be reported to the caller.
  return new Promise<void>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", url);

    xhr.setRequestHeader("Content-Type", contentType);

    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && onProgress) {
        onProgress({
          loaded: event.loaded,
          total: event.total,
          percent: Math.round((event.loaded / event.total) * 100),
        });
      }
    };

    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve();
      } else {
        reject(
          new Error(
            `Upload to R2 failed (status ${xhr.status}). Please try again.`,
          ),
        );
      }
    };

    xhr.onerror = () => {
      reject(
        new Error("Upload to R2 failed — network error. Please try again."),
      );
    };

    xhr.send(file);
  });
}

/**
 * Upload a local file to R2 via a presigned URL and automatically trigger
 * document processing once the upload completes.
 *
 * The file is streamed straight from the browser to object storage; the
 * API is only used to mint the presigned URL and, afterwards, to dispatch
 * the processing job. The two steps are chained so a successful upload
 * always leads straight into processing with no further user action.
 *
 * @param file    The local file selected by the user.
 * @param options See `UploadOptions`. `autoProcess` defaults to `true`.
 * @returns The upload metadata plus the processing-dispatch outcome.
 * @throws If the context can't be resolved, the presigned URL request
 *         fails, or the PUT to R2 fails.
 */
export async function uploadFileToR2(
  file: File,
  options: UploadOptions = {},
): Promise<UploadResult> {
  const { onProgress, autoProcess = true } = options;

  const { organizationId, userId } = await resolveUploadContext();

  const contentType = file.type || "application/octet-stream";

  // The presigned URL is signed for this exact content type, so the PUT
  // must send an identical `Content-Type` header or R2 rejects it.
  const uploadUrl = await api.getUploadUrl(file.name, {
    organizationId,
    userId,
    contentType,
  });

  if (!uploadUrl) {
    throw new Error("The API did not return an upload URL.");
  }

  await putFileToR2(uploadUrl.url, contentType, file, onProgress);

  // File is in R2 — dispatch processing automatically. A dispatch failure
  // is captured (not thrown) so the caller can show exactly what happened:
  // the file *was* uploaded, it's just not being processed yet.
  const process = autoProcess
    ? await processUploadedDocument(uploadUrl.job_id)
    : { response: null as ProcessDocumentResponse | null, error: null };

  return { uploadUrl, process };
}
