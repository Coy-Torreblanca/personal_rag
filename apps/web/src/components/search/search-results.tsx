"use client";

import { useState } from "react";
import { Loader2, Search, SearchX } from "lucide-react";
import { DocumentStatus } from "@/lib/api/types";
import type { DocumentSearchResult } from "@/lib/api/types";
import { Card, CardContent } from "@/components/ui/card";
import { DownloadButton } from "@/components/search/download-button";
import { DeleteButton } from "@/components/search/delete-button";
import { DocumentDetailDialog } from "@/components/search/document-dialog";
import {
  FileTypeIcon,
  statusLabel,
  statusColor,
  relevanceColor,
  formatFileSize,
  truncateFilename,
} from "@/components/search/document-helpers";
import { cn } from "@/lib/utils";

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
  const [isDetailsOpen, setIsDetailsOpen] = useState(false);

  return (
    <Card className="group transition-all hover:shadow-md hover:border-ring/40">
      <CardContent className="flex items-start gap-4 p-4">
        {/* Clickable area — opens the document detail dialog. Wrapped in a
            button so it is keyboard-accessible; the download/delete column
            below stays separate. */}
        <button
          type="button"
          onClick={() => setIsDetailsOpen(true)}
          aria-haspopup="dialog"
          aria-label={`View details for ${result.filename}`}
          className="flex min-w-0 flex-1 cursor-pointer items-start gap-4 rounded-lg text-left outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
        >
          {/* File icon */}
          <div className="flex size-12 shrink-0 items-center justify-center rounded-lg border border-border bg-muted/30 transition-colors group-hover:bg-muted/50">
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
        </button>

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

      {/* Detail dialog — metadata, summary, and markdown content */}
      <DocumentDetailDialog
        document={result}
        open={isDetailsOpen}
        onOpenChange={setIsDetailsOpen}
      />
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
