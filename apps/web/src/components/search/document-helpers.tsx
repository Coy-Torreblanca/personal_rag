// ---------------------------------------------------------------------------
// Shared helpers for rendering document search results and the document
// detail dialog. Kept in a separate module (rather than inside
// `search-results.tsx`) so both components can import them without creating
// a circular dependency.
// ---------------------------------------------------------------------------

import {
  FileText,
  FileImage,
  FileSpreadsheet,
  Presentation,
  File,
  FileArchive,
  Code,
} from "lucide-react";
import { DocumentStatus } from "@/lib/api/types";

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
export function FileTypeIcon({
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
export function statusLabel(status: DocumentStatus): string {
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
export function statusColor(status: DocumentStatus): string {
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
export function relevanceColor(score: number): string {
  if (score >= 0.7)
    return "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400";
  if (score >= 0.4) return "bg-amber-500/10 text-amber-600 dark:text-amber-400";
  return "bg-muted text-muted-foreground";
}

/** Format a byte count as a human-readable size (``1.2 MB``). */
export function formatFileSize(bytes: number | null): string {
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
export function truncateFilename(name: string, max = 48): string {
  if (name.length <= max) return name;
  const ext = name.lastIndexOf(".");
  if (ext === -1) return name.slice(0, max - 3) + "…";
  const extStr = name.slice(ext);
  const base = name.slice(0, ext);
  return base.slice(0, max - extStr.length - 3) + "…" + extStr;
}
