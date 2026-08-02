"use client";

import {
  FileText,
  FileImage,
  FileSpreadsheet,
  Presentation,
  File,
  FileArchive,
  Code,
  Loader2,
  Search,
  SearchX,
} from "lucide-react";
import { DocumentStatus } from "@/lib/api/types";
import type { DocumentSearchResult } from "@/lib/api/types";
import { Card, CardContent } from "@/components/ui/card";
import { DownloadButton } from "@/components/search/download-button";
import { DeleteButton } from "@/components/search/delete-button";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Renders the lucide icon matching a document's MIME type / extension hint.
 *
 * The API stores ``file_type`` as a MIME string (e.g. ``application/pdf``)
 * or an extension-like token, so we match on substrings in priority order
 * and fall back to a generic file icon.
 *
 * Declared as a component (rather than a function returning a component
 * reference) so the icon choice happens inside a stable component body —
 * imported icons are rendered directly, keeping references stable across
 * renders and satisfying ``react-hooks/static-components``.
 */
function FileTypeIcon({
  fileType,
  className,
}: {
  fileType: string;
  className?: string;
}) {
  const type = fileType.toLowerCase();

  if (type.includes("pdf")) return <FileText className={className} />;
  if (
    type.includes("image") ||
    type.includes("png") ||
    type.includes("jpg") ||
    type.includes("jpeg") ||
    type.includes("gif") ||
    type.includes("webp")
  ) {
    return <FileImage className={className} />;
  }
  if (
    type.includes("spreadsheet") ||
    type.includes("excel") ||
    type.includes("xls") ||
    type.includes("csv")
  ) {
    return <FileSpreadsheet className={className} />;
  }
  if (
    type.includes("presentation") ||
    type.includes("powerpoint") ||
    type.includes("slides") ||
    type.includes("ppt")
  ) {
    return <Presentation className={className} />;
  }
  if (
    type.includes("zip") ||
    type.includes("tar") ||
    type.includes("gz") ||
    type.includes("rar")
  ) {
    return <FileArchive className={className} />;
  }
  if (
    type.includes("code") ||
    type.includes("json") ||
    type.includes("xml") ||
    type.includes("html") ||
    type.includes("js") ||
    type.includes("ts") ||
    type.includes("py")
  ) {
    return <Code className={className} />;
  }
  return <File className={className} />;
}

/** Human-readable label for each document status. */
function statusLabel(status: DocumentStatus): string {
  switch (status) {
    case "uploading":
      return "Uploading…";
    case "uploaded":
      return "Uploaded";
    case "processing":
      return "Processing…";
    case "processed":
      return "Ready";
    case "error":
      return "Error";
    default:
      return status;
  }
}

/** Tailwind text color for each document status. */
function statusColor(status: DocumentStatus): string {
  switch (status) {
    case "processed":
      return "text-emerald-600 dark:text-emerald-400";
    case "error":
      return "text-red-600 dark:text-red-400";
    case "processing":
    case "uploading":
      return "text-amber-600 dark:text-amber-400";
    default:
      return "text-muted-foreground";
  }
}

/** Badge color tiers for the Cohere relevance score in ``[0, 1]``. */
function relevanceColor(score: number): string {
  if (score >= 0.7)
    return "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400";
  if (score >= 0.4) return "bg-amber-500/10 text-amber-600 dark:text-amber-400";
  return "bg-muted text-muted-foreground";
}

/** Format a byte count as a human-readable size (``1.2 MB``). */
function formatFileSize(bytes: number | null): string {
  if (bytes === null || bytes === undefined) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/**
 * Truncate a filename while preserving its extension.
 *
 * ``my-very-long-report-name-2026-q3-final-version.pdf`` →
 * ``my-very-long-report-name-…-final-version.pdf`` (roughly).
 */
function truncateFilename(name: string, max = 48): string {
  if (name.length <= max) return name;
  const ext = name.lastIndexOf(".");
  if (ext === -1) return name.slice(0, max - 3) + "…";
  const extStr = name.slice(ext);
  const base = name.slice(0, ext);
  return base.slice(0, max - extStr.length - 3) + "…" + extStr;
}

// ---------------------------------------------------------------------------
// Result Card
// ---------------------------------------------------------------------------

function ResultCard({
  result,
  onDocumentDeleted,
}: {
  result: DocumentSearchResult;
  onDocumentDeleted?: (documentId: string) => void;
}) {
  return (
    <Card className="group transition-all hover:shadow-md hover:border-ring/40">
      <CardContent className="flex items-start gap-4 p-4">
        {/* File icon */}
        <div className="flex size-12 shrink-0 items-center justify-center rounded-lg border border-border bg-muted/30">
          <FileTypeIcon
            fileType={result.file_type}
            className="size-6 text-muted-foreground"
          />
        </div>

        {/* Details */}
        <div className="min-w-0 flex-1 space-y-1">
          <div className="flex items-start justify-between gap-2">
            <h4 className="truncate text-sm font-medium leading-snug">
              {truncateFilename(result.filename)}
            </h4>
            {/* Relevance badge */}
            <span
              className={cn(
                "shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium leading-none",
                relevanceColor(result.relevance),
              )}
            >
              {(result.relevance * 100).toFixed(0)}%
            </span>
          </div>

          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
            <span className={cn("font-medium", statusColor(result.status))}>
              {statusLabel(result.status)}
            </span>
            {result.file_size != null && (
              <span>{formatFileSize(result.file_size)}</span>
            )}
            <span className="uppercase">{result.file_type}</span>
          </div>
        </div>

        {/* Download + delete — download is disabled while the file is still
            being uploaded to R2; deleting is always allowed. */}
        <div className="flex flex-col items-end gap-1">
          <DownloadButton
            documentId={result.id}
            filename={result.filename}
            disabled={result.status === DocumentStatus.UPLOADING}
          />
          <DeleteButton
            documentId={result.id}
            filename={result.filename}
            onDeleted={onDocumentDeleted}
          />
        </div>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Results List
// ---------------------------------------------------------------------------

interface SearchResultsProps {
  /** Search results; ``null`` means no completed search yet. */
  results: DocumentSearchResult[] | null;
  /** True while a search request is in flight. */
  isSearching: boolean;
  /** The query the current results (or empty state) belong to. */
  query: string;
  /** Called with a document id after that document has been deleted. */
  onDocumentDeleted?: (documentId: string) => void;
}

/**
 * Renders one of four states: idle prompt, loading, empty, or results.
 *
 * The states are mutually exclusive and checked in a fixed order, which
 * lets us narrow ``results`` to a non-null array in the final branch.
 */
export function SearchResults({
  results,
  isSearching,
  query,
  onDocumentDeleted,
}: SearchResultsProps) {
  // Initial state — no search performed yet
  if (!isSearching && results === null) {
    return (
      <div className="flex flex-col items-center gap-3 py-24 text-center">
        <Search className="size-12 text-muted-foreground/40" />
        <p className="text-sm text-muted-foreground">
          Enter a query above to search your documents
        </p>
      </div>
    );
  }

  // Loading state
  if (isSearching) {
    return (
      <div className="flex flex-col items-center gap-3 py-24 text-center">
        <Loader2 className="size-8 animate-spin text-muted-foreground/60" />
        <p className="text-sm text-muted-foreground">Searching…</p>
      </div>
    );
  }

  // Defensive narrowing: if results were null while not searching, the
  // idle-state guard above would already have returned. This branch is
  // unreachable at runtime but lets the type checker narrow ``results``
  // to ``DocumentSearchResult[]`` for the branches below.
  if (results === null) {
    return null;
  }

  // Empty results
  if (results.length === 0) {
    return (
      <div className="flex flex-col items-center gap-3 py-24 text-center">
        <SearchX className="size-12 text-muted-foreground/40" />
        <p className="text-sm font-medium">No results found</p>
        <p className="text-sm text-muted-foreground max-w-sm">
          No documents matched &ldquo;{query}&rdquo;. Try a different search
          term.
        </p>
      </div>
    );
  }

  // Results
  return (
    <div className="w-full max-w-2xl space-y-3">
      <p className="text-sm text-muted-foreground">
        {results.length} result{results.length !== 1 ? "s" : ""} for{" "}
        <span className="font-medium text-foreground">
          &ldquo;{query}&rdquo;
        </span>
      </p>
      <div className="space-y-2">
        {results.map((result) => (
          <ResultCard
            key={result.id + result.filename}
            result={result}
            onDocumentDeleted={onDocumentDeleted}
          />
        ))}
      </div>
    </div>
  );
}
