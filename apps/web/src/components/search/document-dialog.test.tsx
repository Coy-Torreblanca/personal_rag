// @vitest-environment jsdom
// ---------------------------------------------------------------------------
// Component tests for `DocumentDetailDialog`.
//
// The API client and the headless base-ui dialog are mocked so the dialog
// can be tested in isolation:
//
//   closed (no fetch) → open (fetch) → metadata + summary + markdown
//                                   └──▶ error banner → retry → content
//
// The base-ui dialog is replaced with a minimal wrapper (like the Button
// mock in the download/upload tests) so tests don't depend on the UI
// library's DOM behaviour (portals, focus trapping, floating-ui).
// ---------------------------------------------------------------------------

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { DocumentDetailDialog } from "./document-dialog";
import { DocumentStatus } from "@/lib/api/types";
import type { DocumentDetail, DocumentSearchResult } from "@/lib/api/types";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const apiMock = vi.hoisted(() => ({
  api: {
    getDocument: vi.fn(),
  },
}));

vi.mock("@/lib/api/client", () => apiMock);

vi.mock("@/components/ui/dialog", () => {
  const Dialog = ({
    open,
    children,
  }: {
    open?: boolean;
    children?: React.ReactNode;
  }) => (open ? <div data-testid="dialog">{children}</div> : null);

  return {
    Dialog,
    DialogBackdrop: () => null,
    DialogPortal: ({ children }: { children?: React.ReactNode }) => (
      <>{children}</>
    ),
    DialogClose: ({
      children,
      ...props
    }: React.ButtonHTMLAttributes<HTMLButtonElement>) => (
      <button {...props}>{children}</button>
    ),
    DialogDescription: ({ children }: { children?: React.ReactNode }) => (
      <p>{children}</p>
    ),
    DialogPopup: ({ children }: { children?: React.ReactNode }) => (
      <div>{children}</div>
    ),
    DialogTitle: ({ children }: { children?: React.ReactNode }) => (
      <h2>{children}</h2>
    ),
  };
});

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const SEARCH_RESULT: DocumentSearchResult = {
  id: "doc-1",
  organization_id: "org-1",
  user_id: "user-1",
  filename: "quarterly-report.pdf",
  s3_key: "org-1/quarterly-report.pdf",
  file_type: "application/pdf",
  file_size: 2048,
  status: DocumentStatus.PROCESSED,
  created_at: "2026-08-01T10:00:00Z",
  updated_at: "2026-08-02T10:00:00Z",
  relevance: 0.82,
};

const DETAIL: DocumentDetail = {
  ...SEARCH_RESULT,
  meta_data: {},
  summary: "Quarterly financial results with strong revenue growth.",
  markdown_content: "# Quarterly Report\n\nRevenue grew 12%.",
};

// ---------------------------------------------------------------------------
// Setup / teardown
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  cleanup();
});

function renderDialog(open = true) {
  const onOpenChange = vi.fn();
  render(
    <DocumentDetailDialog
      document={SEARCH_RESULT}
      open={open}
      onOpenChange={onOpenChange}
    />,
  );
  return { onOpenChange };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("DocumentDetailDialog", () => {
  it("fetches and shows metadata, summary, and markdown content", async () => {
    apiMock.api.getDocument.mockResolvedValue(DETAIL);
    renderDialog();

    // Metadata from the search result renders immediately…
    expect(screen.getByText("quarterly-report.pdf")).toBeTruthy();
    expect(screen.getByText("Ready")).toBeTruthy();
    expect(screen.getByText("application/pdf")).toBeTruthy();
    expect(screen.getByText("82%")).toBeTruthy();

    // …then the fetched summary and markdown appear.
    expect(
      await screen.findByText(
        "Quarterly financial results with strong revenue growth.",
      ),
    ).toBeTruthy();
    expect(screen.getByText(/Quarterly Report/)).toBeTruthy();
    expect(screen.getByText(/Revenue grew 12%/)).toBeTruthy();

    expect(apiMock.api.getDocument).toHaveBeenCalledTimes(1);
    expect(apiMock.api.getDocument).toHaveBeenCalledWith("doc-1");
  });

  it("does not fetch while the dialog is closed", () => {
    renderDialog(false);

    expect(screen.queryByTestId("dialog")).toBeNull();
    expect(apiMock.api.getDocument).not.toHaveBeenCalled();
  });

  it("shows a loading state while the detail is being fetched", () => {
    apiMock.api.getDocument.mockReturnValue(new Promise(() => {}));
    renderDialog();

    expect(screen.getByText("Loading document details…")).toBeTruthy();
  });

  it("shows placeholders when summary and markdown are not available", async () => {
    apiMock.api.getDocument.mockResolvedValue({
      ...DETAIL,
      summary: null,
      markdown_content: null,
    });
    renderDialog();

    expect(
      await screen.findByText("No summary available yet."),
    ).toBeTruthy();
    expect(
      screen.getByText("Markdown content is not available yet."),
    ).toBeTruthy();
  });

  it("shows the summary but a placeholder when only markdown is missing", async () => {
    // Documents that are summarised but whose markdown object is missing
    // (or not yet written) must still render the summary — the two
    // sections are independent.
    apiMock.api.getDocument.mockResolvedValue({
      ...DETAIL,
      markdown_content: null,
    });
    renderDialog();

    expect(
      await screen.findByText(
        "Quarterly financial results with strong revenue growth.",
      ),
    ).toBeTruthy();
    expect(
      screen.getByText("Markdown content is not available yet."),
    ).toBeTruthy();
    // No copy button when there is no markdown to copy.
    expect(screen.queryByRole("button", { name: /copy/i })).toBeNull();
  });

  it("surfaces a fetch error with a working retry button", async () => {
    apiMock.api.getDocument
      .mockRejectedValueOnce(new Error("boom"))
      .mockResolvedValueOnce(DETAIL);
    renderDialog();

    // Error banner with the failure message.
    expect(await screen.findByText("Couldn't load details")).toBeTruthy();
    expect(screen.getByText("boom")).toBeTruthy();
    expect(screen.queryByText(/Quarterly financial results/)).toBeNull();

    // Retry re-runs the request and renders the content.
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(
      await screen.findByText(
        "Quarterly financial results with strong revenue growth.",
      ),
    ).toBeTruthy();
    expect(apiMock.api.getDocument).toHaveBeenCalledTimes(2);
  });

  it("keeps showing the search-result metadata when the fetch fails", async () => {
    apiMock.api.getDocument.mockRejectedValue(new Error("boom"));
    renderDialog();

    expect(await screen.findByText("Couldn't load details")).toBeTruthy();
    // Metadata comes from the search result, so it survives the failure.
    expect(screen.getByText("quarterly-report.pdf")).toBeTruthy();
    expect(screen.getByText("Ready")).toBeTruthy();
  });

  it("does not falsely report a copy when the Clipboard API is unavailable", async () => {
    // jsdom has no Clipboard API, so ``navigator.clipboard`` is undefined
    // here — the button must stay in its default state instead of showing
    // "Copied" for a write that never happened.
    apiMock.api.getDocument.mockResolvedValue(DETAIL);
    renderDialog();

    const copyButton = await screen.findByRole("button", { name: "Copy" });
    fireEvent.click(copyButton);
    expect(screen.queryByRole("button", { name: "Copied" })).toBeNull();
  });

  it("shows a temporary acknowledgement after a successful copy", async () => {
    // Provide a working Clipboard API for this test only.
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(window.navigator, "clipboard", {
      value: { writeText },
      configurable: true,
    });

    try {
      apiMock.api.getDocument.mockResolvedValue(DETAIL);
      renderDialog();

      fireEvent.click(await screen.findByRole("button", { name: "Copy" }));
      expect(writeText).toHaveBeenCalledWith(DETAIL.markdown_content);
      expect(
        await screen.findByRole("button", { name: "Copied" }),
      ).toBeTruthy();
    } finally {
      // Restore so other tests see the clipboard as unavailable again.
      Object.defineProperty(window.navigator, "clipboard", {
        value: undefined,
        configurable: true,
      });
    }
  });

  it("refetches the detail when the dialog is reopened", async () => {
    // The dialog body is keyed by open state, so closing and reopening
    // must remount it and issue a fresh request — the user expects to see
    // a summary that finished processing in the meantime.
    apiMock.api.getDocument.mockResolvedValue(DETAIL);
    const onOpenChange = vi.fn();
    const props = { document: SEARCH_RESULT, onOpenChange } as const;

    const { rerender } = render(
      <DocumentDetailDialog {...props} open={false} />,
    );
    expect(apiMock.api.getDocument).not.toHaveBeenCalled();

    rerender(<DocumentDetailDialog {...props} open={true} />);
    expect(
      await screen.findByText(
        "Quarterly financial results with strong revenue growth.",
      ),
    ).toBeTruthy();
    expect(apiMock.api.getDocument).toHaveBeenCalledTimes(1);

    // Close, reopen, and verify a second request goes out.
    rerender(<DocumentDetailDialog {...props} open={false} />);
    rerender(<DocumentDetailDialog {...props} open={true} />);
    expect(
      await screen.findByText(
        "Quarterly financial results with strong revenue growth.",
      ),
    ).toBeTruthy();
    expect(apiMock.api.getDocument).toHaveBeenCalledTimes(2);
  });
});
