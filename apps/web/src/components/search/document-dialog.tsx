"use client";

import { useCallback, useEffect, useState } from "react";
import {
  AlertCircle,
  Check,
  Copy,
  Loader2,
  RefreshCw,
  X,
} from "lucide-react";
import { api } from "@/lib/api/client";
import type { DocumentDetail, DocumentSearchResult } from "@/lib/api/types";
import {
  Dialog,
  DialogBackdrop,
  DialogClose,
  DialogDescription,
  DialogPopup,
  DialogPortal,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  formatFileSize,
  relevanceColor,
  statusColor,
  statusLabel,
} from "@/components/search/document-helpers";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Format an ISO timestamp for display (``Aug 7, 2026, 2:30 PM``). */
function formatDateTime(value: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

// ---------------------------------------------------------------------------
// Document Detail Dialog
// ---------------------------------------------------------------------------

interface DocumentDetailDialogProps {
  /** The search result that was clicked — provides instant metadata while
      the full detail (summary + markdown) loads. */
  document: DocumentSearchResult;
  /** Whether the dialog is open. */
  open: boolean;
  /** Called when the dialog should open/close. */
  onOpenChange: (open: boolean) => void;
}

/**
 * Modal showing everything the backend knows about a document: its
 * metadata, the LLM-generated summary, and the processed markdown content.
 *
 * The full detail (summary + markdown) is fetched on open from
 * ``GET /api/documents/{id}``; the search result is rendered immediately
 * so the dialog never appears empty. A failure surfaces an inline error
 * with a retry button rather than an empty dialog.
 */
export function DocumentDetailDialog({
  document,
  open,
  onOpenChange,
}: DocumentDetailDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogPortal>
        <DialogBackdrop />
        <DialogPopup className="flex max-h-[min(85vh,48rem)] w-full max-w-2xl flex-col gap-0 overflow-hidden p-0">
          {/* Keyed by open state so every open remounts the content with
              fresh state — no stale summary/markdown from a previous visit. */}
          <DocumentDetailContent
            key={open ? `open-${document.id}` : `closed-${document.id}`}
            document={document}
          />
        </DialogPopup>
      </DialogPortal>
    </Dialog>
  );
}

/**
 * Dialog body: header, metadata, summary, and markdown content.
 *
 * Rendered as a separate component so it can be keyed/remounted whenever
 * the dialog opens, which resets the fetch state without effect-driven
 * setState calls.
 */
function DocumentDetailContent({
  document,
}: {
  document: DocumentSearchResult;
}) {
  const [detail, setDetail] = useState<DocumentDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;

    void (async () => {
      try {
        const data = await api.getDocument(document.id);
        if (!cancelled) setDetail(data ?? null);
      } catch (err) {
        if (!cancelled) {
          setError(
            err instanceof Error ? err.message : "An unexpected error occurred",
          );
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [document.id, reloadKey]);

  // Loading until the fetch settles: no detail yet and no failure.
  const isLoading = detail === null && error === null;

  const handleRetry = useCallback(() => {
    setError(null);
    setReloadKey((key) => key + 1);
  }, []);

  // Prefer the fetched detail; fall back to the search result's metadata
  // while loading or when the fetch failed.
  const meta = detail ?? document;

  return (
    <>
      {/* Header */}
      <div className="flex shrink-0 items-start justify-between gap-4 border-b border-border p-5">
        <div className="min-w-0">
          <DialogTitle className="truncate text-base leading-snug">
            {document.filename}
          </DialogTitle>
          <DialogDescription className="mt-1">
            Metadata, summary, and markdown content
          </DialogDescription>
        </div>
        <DialogClose className="cursor-pointer rounded-md p-1.5 text-muted-foreground outline-none transition-colors hover:bg-muted hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50">
          <X className="size-4" />
          <span className="sr-only">Close</span>
        </DialogClose>
      </div>

      {/* Body */}
      <div className="flex-1 space-y-6 overflow-y-auto p-5">
        {/* Metadata */}
        <section aria-labelledby="document-metadata-heading">
          <h3
            id="document-metadata-heading"
            className="mb-2 text-sm font-semibold"
          >
            Metadata
          </h3>
          <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-1.5 text-sm">
            <dt className="text-muted-foreground">Status</dt>
            <dd className={cn("font-medium", statusColor(meta.status))}>
              {statusLabel(meta.status)}
            </dd>

            <dt className="text-muted-foreground">File type</dt>
            <dd className="uppercase">{meta.file_type}</dd>

            <dt className="text-muted-foreground">Size</dt>
            <dd>{formatFileSize(meta.file_size) || "—"}</dd>

            <dt className="text-muted-foreground">Created</dt>
            <dd>{formatDateTime(meta.created_at)}</dd>

            <dt className="text-muted-foreground">Updated</dt>
            <dd>{formatDateTime(meta.updated_at)}</dd>

            <dt className="text-muted-foreground">Document ID</dt>
            <dd className="break-all font-mono text-xs leading-relaxed">
              {meta.id}
            </dd>

            <dt className="text-muted-foreground">Relevance</dt>
            <dd>
              <span
                className={cn(
                  "rounded-full px-2 py-0.5 text-[11px] font-medium leading-none",
                  relevanceColor(document.relevance),
                )}
              >
                {(document.relevance * 100).toFixed(0)}%
              </span>
            </dd>
          </dl>
        </section>

        {/* Summary + markdown — loading / error / content */}
        {isLoading ? (
          <div className="flex items-center gap-2 py-8 text-sm text-muted-foreground">
            <Loader2 className="size-4 animate-spin" />
            Loading document details…
          </div>
        ) : error ? (
          <div
            role="alert"
            className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-800/40 dark:bg-red-950/30 dark:text-red-400"
          >
            <div className="flex items-center gap-2">
              <AlertCircle className="size-4 shrink-0" />
              <span className="font-medium">Couldn&apos;t load details</span>
            </div>
            <p className="mt-1 text-xs opacity-80">{error}</p>
            <button
              type="button"
              onClick={handleRetry}
              className="mt-2 inline-flex cursor-pointer items-center gap-1.5 rounded-md border border-red-300 bg-white px-2 py-1 text-xs font-medium text-red-700 outline-none transition-colors hover:bg-red-100 focus-visible:ring-3 focus-visible:ring-red-300/50 dark:border-red-700 dark:bg-transparent dark:text-red-400 dark:hover:bg-red-950/50"
            >
              <RefreshCw className="size-3" />
              Retry
            </button>
          </div>
        ) : (
          <>
            {/* Summary */}
            <section aria-labelledby="document-summary-heading">
              <h3
                id="document-summary-heading"
                className="mb-2 text-sm font-semibold"
              >
                Summary
              </h3>
              {detail?.summary ? (
                <p className="whitespace-pre-wrap text-sm leading-relaxed">
                  {detail.summary}
                </p>
              ) : (
                <p className="text-sm text-muted-foreground">
                  No summary available yet.
                </p>
              )}
            </section>

            {/* Markdown content */}
            <section aria-labelledby="document-markdown-heading">
              <div className="mb-2 flex items-center justify-between gap-2">
                <h3
                  id="document-markdown-heading"
                  className="text-sm font-semibold"
                >
                  Markdown content
                </h3>
                {detail?.markdown_content && (
                  <CopyMarkdownButton content={detail.markdown_content} />
                )}
              </div>
              {detail?.markdown_content ? (
                <pre className="rounded-lg border border-border bg-muted/30 p-4 font-mono text-xs leading-relaxed whitespace-pre-wrap break-words">
                  {detail.markdown_content}
                </pre>
              ) : (
                <p className="text-sm text-muted-foreground">
                  Markdown content is not available yet.
                </p>
              )}
            </section>
          </>
        )}
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// Copy button
// ---------------------------------------------------------------------------

/** Copies the markdown content to the clipboard, showing a check on success. */
function CopyMarkdownButton({ content }: { content: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard?.writeText(content);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard unavailable (e.g. non-secure context) — ignore silently.
    }
  }, [content]);

  return (
    <button
      type="button"
      onClick={() => void handleCopy()}
      className="inline-flex cursor-pointer items-center gap-1.5 rounded-md border border-border px-2 py-1 text-xs font-medium text-muted-foreground outline-none transition-colors hover:bg-muted hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50"
    >
      {copied ? (
        <Check className="size-3 text-emerald-600 dark:text-emerald-400" />
      ) : (
        <Copy className="size-3" />
      )}
      {copied ? "Copied" : "Copy"}
    </button>
  );
}
