"use client";

import { useState } from "react";
import { Download, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api/client";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface DownloadButtonProps {
  /** Document id used to request a presigned download URL. */
  documentId: string;
  /** Original filename — used for the downloaded file. */
  filename: string;
  /**
   * Disable the button while the file is not yet available in object
   * storage (e.g. the upload is still in flight).
   */
  disabled?: boolean;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

/**
 * Icon button that downloads a document's original file from R2.
 *
 * The download happens in three steps, all from the browser:
 *
 * 1. ``GET /api/documents/{id}/download`` returns a time-limited presigned
 *    GET URL for the object.
 * 2. The bytes are fetched cross-origin (the bucket CORS policy allows
 *    ``GET`` — see ``docs/INFRASTRUCTURE.md``), so the file never needs to
 *    pass through the API server.
 * 3. The bytes are wrapped in a same-origin ``blob:`` URL and handed to a
 *    temporary anchor with the original filename, which guarantees a real
 *    download (the ``download`` attribute would be ignored on a
 *    cross-origin URL) without navigating away from the page.
 *
 * While a download is in flight the button is disabled and shows a spinner;
 * failures are surfaced as a compact inline message under the button.
 */
export function DownloadButton({
  documentId,
  filename,
  disabled = false,
}: DownloadButtonProps) {
  const [isDownloading, setIsDownloading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleDownload() {
    setError(null);
    setIsDownloading(true);

    try {
      // 1. Presigned GET URL from the API (expires after an hour).
      const response = await api.downloadDocument(documentId);
      if (!response?.url) {
        throw new Error("The API did not return a download URL.");
      }

      // 2. Fetch the file bytes directly from object storage.
      const res = await fetch(response.url);
      if (!res.ok) {
        throw new Error(`Download failed (status ${res.status})`);
      }
      const blob = await res.blob();

      // 3. Trigger the browser download via a same-origin blob URL so the
      //    original filename is preserved even though the file lives on
      //    another origin.
      const objectUrl = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = objectUrl;
      anchor.download = filename;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();

      // Give the browser a tick to start the download before freeing the
      // blob URL — revoking synchronously can abort the download.
      setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "An unexpected error occurred";
      console.error(`[download] Failed to download "${filename}":`, err);
      setError(message);
    } finally {
      setIsDownloading(false);
    }
  }

  return (
    <div className="flex flex-col items-end gap-1">
      <Button
        type="button"
        variant="ghost"
        size="icon-sm"
        onClick={handleDownload}
        disabled={disabled || isDownloading}
        aria-label={`Download ${filename}`}
        title={`Download ${filename}`}
      >
        {isDownloading ? (
          <Loader2 className="size-4 animate-spin" />
        ) : (
          <Download className="size-4" />
        )}
      </Button>

      {/* Compact failure message — role="alert" so screen readers announce
          download failures without user interaction. */}
      {error && (
        <span
          role="alert"
          className="max-w-40 text-right text-[11px] leading-tight text-red-600 dark:text-red-400"
        >
          {error}
        </span>
      )}
    </div>
  );
}
