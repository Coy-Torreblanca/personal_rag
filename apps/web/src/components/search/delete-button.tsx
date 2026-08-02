"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Loader2, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api/client";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface DeleteButtonProps {
  /** Document id passed to `DELETE /api/documents/{id}`. */
  documentId: string;
  /** Original filename — used for the accessible label. */
  filename: string;
  /** Called with the document id after a successful delete. */
  onDeleted?: (documentId: string) => void;
}

/** How long the confirmation state stays armed before resetting. */
const CONFIRM_RESET_MS = 4000;

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

/**
 * Icon button that deletes a document (record, processing jobs, and the
 * files in R2) via `DELETE /api/documents/{id}`.
 *
 * Deleting is destructive, so it uses a two-step confirmation: the first
 * click arms the button (it turns into a small destructive "Delete?"
 * button), and only the second click actually deletes. The confirmation
 * auto-resets after a few seconds (or on ``Escape``), so a stale armed
 * button can never delete a document by accident later. Focus moves to the
 * confirm button while armed and returns to the trash button when the
 * confirmation is dismissed.
 *
 * While the request is in flight the button is disabled and shows a
 * spinner; failures are surfaced as a compact inline message. On success
 * ``onDeleted`` fires so the parent can remove the card from the list.
 */
export function DeleteButton({
  documentId,
  filename,
  onDeleted,
}: DeleteButtonProps) {
  const [phase, setPhase] = useState<"idle" | "confirming" | "deleting">(
    "idle",
  );
  const [error, setError] = useState<string | null>(null);

  // Handle to the pending auto-reset timer (cleared on unmount/phase change).
  const confirmTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Guards against a second activation while a delete is already in flight
  // (e.g. a double-click that lands before React re-renders the button).
  const inFlightRef = useRef(false);
  // Lets us return focus to the trash button when the confirmation is
  // dismissed, so keyboard/screen-reader users never lose their place.
  const trashButtonRef = useRef<HTMLButtonElement | null>(null);
  // Remembers that we were confirming so focus can be restored once the
  // confirmation is dismissed (see the focus-restore effect below).
  const wasConfirmingRef = useRef(false);

  /**
   * Dismiss the armed confirmation. Shared by the auto-reset timer and the
   * Escape key; focus restoration happens in the effect below because the
   * trash button is unmounted while confirming and must be re-mounted first.
   */
  const cancelConfirmation = useCallback(() => {
    setPhase("idle");
  }, []);

  // Auto-reset the armed confirmation so it can't linger indefinitely.
  useEffect(() => {
    if (phase !== "confirming") return;
    confirmTimer.current = setTimeout(
      cancelConfirmation,
      CONFIRM_RESET_MS,
    );
    // Clearing on cleanup covers both unmount and leaving the confirming
    // phase (e.g. the user confirmed or hit Escape) — a stale timer must
    // never fire after the button is no longer armed.
    return () => {
      if (confirmTimer.current) clearTimeout(confirmTimer.current);
    };
  }, [phase, cancelConfirmation]);

  // Restore focus to the trash button whenever the confirmation is dismissed
  // (Escape, auto-reset, or a failed delete). Runs as an effect — after the
  // DOM update — so the trash button is guaranteed to be mounted (and the
  // ref attached) again before we focus it. Focusing a detached node would
  // silently no-op.
  useEffect(() => {
    if (phase === "confirming") {
      wasConfirmingRef.current = true;
    } else if (phase === "idle" && wasConfirmingRef.current) {
      wasConfirmingRef.current = false;
      trashButtonRef.current?.focus();
    }
  }, [phase]);

  async function handleDelete() {
    // Re-entry guard: ignore any activation while a request is in flight.
    if (inFlightRef.current) return;
    inFlightRef.current = true;
    setError(null);
    setPhase("deleting");

    try {
      await api.deleteDocument(documentId);
      // The parent removes the card, unmounting this component.
      onDeleted?.(documentId);
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "An unexpected error occurred";
      console.error(`[delete] Failed to delete "${filename}":`, err);
      setError(message);
      // Back to idle; the focus-restore effect returns focus to the trash
      // button so the user can retry.
      setPhase("idle");
    } finally {
      // Released even on success — the component may stay mounted if the
      // parent chooses not to unmount it.
      inFlightRef.current = false;
    }
  }

  return (
    <div className="flex flex-col items-end gap-1">
      {phase === "confirming" ? (
        <Button
          type="button"
          variant="destructive"
          size="sm"
          onClick={handleDelete}
          onKeyDown={(e) => {
            // Escape dismisses the confirmation without deleting — standard
            // behaviour for destructive confirmations.
            if (e.key === "Escape") {
              e.preventDefault();
              cancelConfirmation();
            }
          }}
          // Keep the document in the accessible name even though the visible
          // label is the generic "Delete?".
          aria-label={`Confirm deletion of ${filename}`}
          title={`Delete ${filename}?`}
          autoFocus
        >
          Delete?
        </Button>
      ) : (
        <Button
          ref={trashButtonRef}
          type="button"
          variant="ghost"
          size="icon-sm"
          onClick={() => {
            setError(null);
            setPhase("confirming");
          }}
          disabled={phase === "deleting"}
          aria-label={`Delete ${filename}`}
          title={`Delete ${filename}`}
          className="hover:text-destructive hover:bg-destructive/10 dark:hover:bg-destructive/20"
        >
          {phase === "deleting" ? (
            <Loader2 className="size-4 animate-spin" />
          ) : (
            <Trash2 className="size-4" />
          )}
        </Button>
      )}

      {/* Compact failure message — role="alert" so screen readers announce
          delete failures without user interaction. */}
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
