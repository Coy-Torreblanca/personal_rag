"use client";

import { useRef, useState, type ChangeEvent } from "react";
import { Upload, Loader2, Check, X, TriangleAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  processUploadedDocument,
  toErrorMessage,
  uploadFileToR2,
  type UploadProgress,
} from "@/lib/api/upload";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Discriminated union describing the current upload state. */
type UploadStatus =
  | { kind: "idle" }
  | { kind: "uploading"; percent: number | null; filename: string }
  | { kind: "success"; filename: string }
  | {
      kind: "partial";
      filename: string;
      jobId: string;
      message: string;
      retrying: boolean;
    }
  | { kind: "error"; message: string };

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

/**
 * Upload button that sends a locally selected file straight to R2 and
 * automatically triggers document processing once the upload completes.
 *
 * Clicking the button opens a file picker. Once a file is chosen it is
 * uploaded directly to object storage via a presigned URL (the file never
 * passes through the API server), with live progress feedback, and the
 * processing job is dispatched automatically right afterwards.
 *
 * State model:
 * - ``idle``       → nothing has been uploaded yet
 * - ``uploading``  → an upload is in flight (button is disabled)
 * - ``success``    → file uploaded **and** processing dispatched
 * - ``partial``    → file uploaded, but processing dispatch failed
 *                    (retryable from the banner)
 * - ``error``      → the upload itself failed (message shown in a banner)
 */
export function UploadButton() {
  const inputRef = useRef<HTMLInputElement>(null);
  const [status, setStatus] = useState<UploadStatus>({ kind: "idle" });

  const isUploading = status.kind === "uploading";

  function openFilePicker() {
    // Programmatically open the hidden <input type="file">. The input is
    // `display: none`, so clicking it directly is the standard pattern.
    inputRef.current?.click();
  }

  /**
   * Retry just the processing dispatch for an already-uploaded file.
   *
   * `processUploadedDocument` already retries transient failures internally,
   * so this is the user-driven, last-resort retry for a permanently failed
   * dispatch. Success moves the banner to `success`; a fresh failure keeps
   * the banner in `partial` with an updated message.
   */
  async function retryProcessing(
    partial: Extract<UploadStatus, { kind: "partial" }>,
  ) {
    setStatus({ ...partial, retrying: true });

    const outcome = await processUploadedDocument(partial.jobId);

    if (outcome.error) {
      console.error(
        `[upload] Processing retry failed for job ${partial.jobId}: ${outcome.error}`,
      );
      setStatus({ ...partial, retrying: false, message: outcome.error });
    } else {
      console.debug(
        `[upload] Processing retry succeeded for job ${partial.jobId}`,
      );
      setStatus({ kind: "success", filename: partial.filename });
    }
  }

  /**
   * Entry point for a newly selected file: upload to R2, then dispatch
   * processing. Every terminal state (success / partial / error) is
   * surfaced through the status banners below.
   */
  async function handleFileChange(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    // Reset the input so selecting the same file again re-fires `change`.
    e.target.value = "";
    if (!file) return;

    setStatus({ kind: "uploading", percent: null, filename: file.name });

    try {
      // Stream progress into state as the PUT to R2 progresses.
      const onProgress = (progress: UploadProgress) =>
        setStatus({
          kind: "uploading",
          percent: progress.percent,
          filename: file.name,
        });

      const { uploadUrl, process } = await uploadFileToR2(file, { onProgress });

      if (process.error) {
        // The file made it to R2 but processing didn't start — surface the
        // exact state instead of pretending the whole operation failed.
        console.warn(
          `[upload] "${file.name}" uploaded but processing failed to start: ${process.error}`,
        );
        setStatus({
          kind: "partial",
          filename: file.name,
          jobId: uploadUrl.job_id,
          message: process.error,
          retrying: false,
        });
      } else {
        setStatus({ kind: "success", filename: file.name });
      }
    } catch (err) {
      // The upload itself failed — the error message is already shown in
      // the banner, but log the full error for diagnostics.
      const message = toErrorMessage(err);
      console.error(`[upload] Upload failed for "${file.name}":`, err);
      setStatus({ kind: "error", message });
    }
  }

  return (
    <div className="flex flex-col items-end gap-2">
      <Button
        type="button"
        variant="outline"
        size="lg"
        onClick={openFilePicker}
        disabled={isUploading}
      >
        {isUploading ? (
          <Loader2 className="size-4 animate-spin" />
        ) : (
          <Upload className="size-4" />
        )}
        {isUploading
          ? status.percent !== null
            ? `Uploading ${status.percent}%`
            : "Uploading…"
          : "Upload"}
      </Button>

      {/* Hidden file input driven by the button */}
      <input
        ref={inputRef}
        type="file"
        className="hidden"
        onChange={handleFileChange}
        disabled={isUploading}
      />

      {/* Status banners — role="status" + aria-live so screen readers
          announce upload completion / failures without user interaction. */}
      {status.kind === "success" && (
        <div
          role="status"
          aria-live="polite"
          className="flex w-full max-w-md items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-700 dark:border-emerald-800/40 dark:bg-emerald-950/30 dark:text-emerald-400"
        >
          <Check className="size-3.5 shrink-0" />
          <span className="truncate">
            {status.filename} uploaded — processing started
          </span>
          <button
            type="button"
            onClick={() => setStatus({ kind: "idle" })}
            className="ml-auto shrink-0 rounded p-0.5 text-emerald-600 hover:bg-emerald-100 dark:text-emerald-400 dark:hover:bg-emerald-900/40"
            aria-label="Dismiss"
          >
            <X className="size-3.5" />
          </button>
        </div>
      )}

      {/* Upload succeeded but processing dispatch failed — retryable */}
      {status.kind === "partial" && (
        <div
          role="status"
          aria-live="polite"
          className="flex w-full max-w-md items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700 dark:border-amber-800/40 dark:bg-amber-950/30 dark:text-amber-400"
        >
          {status.retrying ? (
            <Loader2 className="size-3.5 shrink-0 animate-spin" />
          ) : (
            <TriangleAlert className="size-3.5 shrink-0" />
          )}
          {/* NB: JSX strips newlines adjacent to expressions, so the space
              between the colon and the message must be explicit ({" "}). */}
          <span className="min-w-0">
            {status.filename} uploaded, but processing didn&apos;t start:{" "}
            {status.message}
          </span>
          {!status.retrying && (
            <button
              type="button"
              onClick={() => retryProcessing(status)}
              className="ml-auto shrink-0 rounded px-1.5 py-0.5 font-medium text-amber-700 hover:bg-amber-100 dark:text-amber-400 dark:hover:bg-amber-900/40"
            >
              Retry
            </button>
          )}
          <button
            type="button"
            onClick={() => setStatus({ kind: "idle" })}
            className="shrink-0 rounded p-0.5 text-amber-600 hover:bg-amber-100 dark:text-amber-400 dark:hover:bg-amber-900/40"
            aria-label="Dismiss"
          >
            <X className="size-3.5" />
          </button>
        </div>
      )}

      {status.kind === "error" && (
        <div
          role="status"
          aria-live="polite"
          className={cn(
            "flex w-full max-w-md items-center gap-2 rounded-lg border border-red-200",
            "bg-red-50 px-3 py-2 text-xs text-red-700",
            "dark:border-red-800/40 dark:bg-red-950/30 dark:text-red-400",
          )}
        >
          <X className="size-3.5 shrink-0" />
          <span className="min-w-0">{status.message}</span>
          <button
            type="button"
            onClick={() => setStatus({ kind: "idle" })}
            className="ml-auto shrink-0 rounded p-0.5 text-red-600 hover:bg-red-100 dark:text-red-400 dark:hover:bg-red-900/40"
            aria-label="Dismiss"
          >
            <X className="size-3.5" />
          </button>
        </div>
      )}
    </div>
  );
}
