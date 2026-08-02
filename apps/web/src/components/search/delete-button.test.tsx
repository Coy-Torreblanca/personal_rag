// @vitest-environment jsdom
// ---------------------------------------------------------------------------
// Component tests for `DeleteButton`.
//
// The API client and the UI `Button` are mocked so the two-step delete
// flow can be tested in isolation:
//
//   idle → (click) → confirming → (click) → deleting → onDeleted
//                                            └──▶ error banner → idle
//
// The confirmation also auto-resets to idle after a timeout, which is
// tested with fake timers.
// ---------------------------------------------------------------------------

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { DeleteButton } from "./delete-button";
import type { DeleteDocumentResponse } from "@/lib/api/types";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const apiMock = vi.hoisted(() => ({
  api: {
    deleteDocument: vi.fn(),
  },
}));

vi.mock("@/lib/api/client", () => apiMock);

// Replace the headless base-ui Button with a plain <button> so the test
// doesn't depend on the UI library's DOM behaviour (same as the other
// component tests). `variant`/`size` are dropped — the real Button uses
// them only for styling.
vi.mock("@/components/ui/button", () => ({
  Button: ({
    children,
    variant,
    size,
    ...props
  }: React.ButtonHTMLAttributes<HTMLButtonElement> & {
    variant?: string;
    size?: string;
  }) => {
    void variant;
    void size;
    return <button {...props}>{children}</button>;
  },
}));

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const DELETE_RESPONSE: DeleteDocumentResponse = {
  success: true,
  message: "Document 'report.pdf' deleted successfully",
  document_id: "doc-1",
};

// Accessible name of the armed confirmation button. The visible label stays
// the generic "Delete?", but an aria-label carries the filename for screen
// readers, so queries must use the full accessible name.
const CONFIRM_LABEL = "Confirm deletion of report.pdf";

// ---------------------------------------------------------------------------
// Setup / teardown
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  // RTL only auto-registers cleanup when vitest globals are enabled; we keep
  // globals off, so unmount the previous tree explicitly to avoid DOM leaks
  // between tests.
  cleanup();
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("DeleteButton", () => {
  it("renders a delete button labelled with the filename", () => {
    render(<DeleteButton documentId="doc-1" filename="report.pdf" />);

    const button = screen.getByRole("button", {
      name: "Delete report.pdf",
    }) as HTMLButtonElement;
    expect(button).toBeTruthy();
    expect(button.disabled).toBe(false);
    // Not armed by default — no confirmation button yet.
    expect(screen.queryByRole("button", { name: CONFIRM_LABEL })).toBeNull();
  });

  it("requires a second click to delete and reports the deleted id", async () => {
    apiMock.api.deleteDocument.mockResolvedValue(DELETE_RESPONSE);
    const onDeleted = vi.fn();

    render(
      <DeleteButton
        documentId="doc-1"
        filename="report.pdf"
        onDeleted={onDeleted}
      />,
    );

    // First click arms the confirmation — nothing is deleted yet.
    fireEvent.click(
      screen.getByRole("button", { name: "Delete report.pdf" }),
    );
    expect(screen.getByRole("button", { name: CONFIRM_LABEL })).toBeTruthy();
    expect(apiMock.api.deleteDocument).not.toHaveBeenCalled();

    // Second click actually deletes.
    fireEvent.click(screen.getByRole("button", { name: CONFIRM_LABEL }));
    await waitFor(() => expect(onDeleted).toHaveBeenCalledWith("doc-1"));
    expect(apiMock.api.deleteDocument).toHaveBeenCalledWith("doc-1");
  });

  it("shows a spinner and disables the button while deleting", async () => {
    let resolveDelete!: (response: DeleteDocumentResponse) => void;
    apiMock.api.deleteDocument.mockReturnValue(
      new Promise<DeleteDocumentResponse>((resolve) => {
        resolveDelete = resolve;
      }),
    );
    const onDeleted = vi.fn();

    render(
      <DeleteButton
        documentId="doc-1"
        filename="report.pdf"
        onDeleted={onDeleted}
      />,
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Delete report.pdf" }),
    );
    fireEvent.click(screen.getByRole("button", { name: CONFIRM_LABEL }));

    // In flight — the button is disabled until the request settles.
    const button = screen.getByRole("button", {
      name: "Delete report.pdf",
    }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);

    await act(async () => {
      resolveDelete(DELETE_RESPONSE);
    });
    expect(onDeleted).toHaveBeenCalledWith("doc-1");
  });

  it("shows an error, resets to idle, and does not report deletion on failure", async () => {
    apiMock.api.deleteDocument.mockRejectedValue(
      new Error("Document not found"),
    );
    const onDeleted = vi.fn();

    render(
      <DeleteButton
        documentId="doc-1"
        filename="report.pdf"
        onDeleted={onDeleted}
      />,
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Delete report.pdf" }),
    );
    fireEvent.click(screen.getByRole("button", { name: CONFIRM_LABEL }));

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Document not found");
    expect(onDeleted).not.toHaveBeenCalled();

    // Back to idle — trash button again, no armed confirmation.
    expect(screen.queryByRole("button", { name: CONFIRM_LABEL })).toBeNull();
    expect(
      screen.getByRole("button", { name: "Delete report.pdf" }),
    ).toBeTruthy();
  });

  it("labels the confirmation with the filename for assistive tech", () => {
    render(<DeleteButton documentId="doc-1" filename="report.pdf" />);
    fireEvent.click(
      screen.getByRole("button", { name: "Delete report.pdf" }),
    );

    // The visible label stays the generic "Delete?", but the accessible name
    // carries the filename so screen-reader users know exactly what they
    // would be deleting before they commit.
    const confirmButton = screen.getByRole("button", {
      name: CONFIRM_LABEL,
    }) as HTMLButtonElement;
    expect(confirmButton.textContent).toBe("Delete?");
    expect(confirmButton.disabled).toBe(false);
  });

  it("cancels the confirmation with Escape and restores focus", () => {
    render(<DeleteButton documentId="doc-1" filename="report.pdf" />);
    fireEvent.click(
      screen.getByRole("button", { name: "Delete report.pdf" }),
    );
    const confirmButton = screen.getByRole("button", {
      name: CONFIRM_LABEL,
    });

    fireEvent.keyDown(confirmButton, { key: "Escape" });

    expect(screen.queryByRole("button", { name: CONFIRM_LABEL })).toBeNull();
    expect(apiMock.api.deleteDocument).not.toHaveBeenCalled();
    // Focus returns to the trash button so keyboard users keep their place.
    expect(document.activeElement).toBe(
      screen.getByRole("button", { name: "Delete report.pdf" }),
    );
  });

  it("clears a previous error when the user re-arms the confirmation", async () => {
    apiMock.api.deleteDocument.mockRejectedValue(new Error("boom"));
    render(<DeleteButton documentId="doc-1" filename="report.pdf" />);

    // First attempt fails → error banner appears.
    fireEvent.click(
      screen.getByRole("button", { name: "Delete report.pdf" }),
    );
    fireEvent.click(screen.getByRole("button", { name: CONFIRM_LABEL }));
    expect(await screen.findByRole("alert")).toBeTruthy();

    // Re-arming clears the stale error so it can't linger next to a fresh
    // confirmation and mislead the user.
    fireEvent.click(
      screen.getByRole("button", { name: "Delete report.pdf" }),
    );
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByRole("button", { name: CONFIRM_LABEL })).toBeTruthy();
  });

  it("auto-resets the armed confirmation after a timeout", () => {
    vi.useFakeTimers();

    render(<DeleteButton documentId="doc-1" filename="report.pdf" />);
    fireEvent.click(
      screen.getByRole("button", { name: "Delete report.pdf" }),
    );
    expect(screen.getByRole("button", { name: CONFIRM_LABEL })).toBeTruthy();

    // After the confirmation window elapses the button returns to idle and
    // nothing was deleted.
    act(() => {
      vi.advanceTimersByTime(4000);
    });
    expect(screen.queryByRole("button", { name: CONFIRM_LABEL })).toBeNull();
    expect(
      screen.getByRole("button", { name: "Delete report.pdf" }),
    ).toBeTruthy();
    expect(apiMock.api.deleteDocument).not.toHaveBeenCalled();
    // Focus is restored to the trash button after the auto-reset.
    expect(document.activeElement).toBe(
      screen.getByRole("button", { name: "Delete report.pdf" }),
    );
  });
});
