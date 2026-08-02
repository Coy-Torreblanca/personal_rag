// @vitest-environment jsdom
// ---------------------------------------------------------------------------
// Component tests for `DownloadButton`.
//
// The API client and the UI `Button` are mocked so the download flow can be
// tested in isolation:
//
//   idle → (click) → fetching presigned URL → fetching bytes → anchor click
//                                                    └──▶ error banner
//
// `URL.createObjectURL`/`revokeObjectURL` don't exist in jsdom, so they are
// stubbed; `fetch` is stubbed as well so no real network request is made.
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
import { DownloadButton } from "./download-button";
import type { DownloadDocumentResponse } from "@/lib/api/types";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const apiMock = vi.hoisted(() => ({
  api: {
    downloadDocument: vi.fn(),
  },
}));

vi.mock("@/lib/api/client", () => apiMock);

const urlApi = vi.hoisted(() => ({
  createObjectURL: vi.fn(() => "blob:mock-url"),
  revokeObjectURL: vi.fn(),
}));

// Replace the headless base-ui Button with a plain <button> so the test
// doesn't depend on the UI library's DOM behaviour (same as the upload
// button tests). `variant`/`size` are dropped — the real Button uses them
// only for styling.
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

const DOWNLOAD_RESPONSE: DownloadDocumentResponse = {
  success: true,
  url: "https://test-bucket.r2.dev/org-1/report.pdf?sig=abc",
  filename: "report.pdf",
  key: "org-1/report.pdf",
  method: "GET",
  expires_in: 3600,
  message: "Presigned URL generated",
};

function okResponse(body = "file-bytes"): Response {
  return {
    ok: true,
    status: 200,
    blob: async () => new Blob([body]),
  } as unknown as Response;
}

// ---------------------------------------------------------------------------
// Setup / teardown
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.clearAllMocks();

  // jsdom doesn't implement the blob URL API — provide deterministic stubs.
  Object.defineProperty(URL, "createObjectURL", {
    value: urlApi.createObjectURL,
    writable: true,
    configurable: true,
  });
  Object.defineProperty(URL, "revokeObjectURL", {
    value: urlApi.revokeObjectURL,
    writable: true,
    configurable: true,
  });

  vi.stubGlobal("fetch", vi.fn(async () => okResponse()));
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  // RTL only auto-registers cleanup when vitest globals are enabled; we keep
  // globals off, so unmount the previous tree explicitly to avoid DOM leaks
  // between tests.
  cleanup();
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("DownloadButton", () => {
  it("renders a download button labelled with the filename", () => {
    render(<DownloadButton documentId="doc-1" filename="report.pdf" />);

    const button = screen.getByRole("button", {
      name: "Download report.pdf",
    }) as HTMLButtonElement;
    expect(button).toBeTruthy();
    expect(button.disabled).toBe(false);
  });

  it("fetches the presigned URL and triggers a download on click", async () => {
    apiMock.api.downloadDocument.mockResolvedValue(DOWNLOAD_RESPONSE);
    const clickSpy = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => {});
    const createElementSpy = vi.spyOn(document, "createElement");

    render(<DownloadButton documentId="doc-1" filename="report.pdf" />);
    fireEvent.click(screen.getByRole("button", { name: "Download report.pdf" }));

    await waitFor(() => expect(clickSpy).toHaveBeenCalledTimes(1));

    // The presigned URL was requested for the right document…
    expect(apiMock.api.downloadDocument).toHaveBeenCalledWith("doc-1");
    // …the bytes were fetched from object storage…
    expect(fetch).toHaveBeenCalledWith(DOWNLOAD_RESPONSE.url);
    // …and wrapped in a blob URL for the anchor.
    expect(urlApi.createObjectURL).toHaveBeenCalledTimes(1);

    // The anchor carries the original filename so the browser saves the
    // file under the right name.
    const anchors = createElementSpy.mock.results
      .map((result) => result.value)
      .filter(
        (el): el is HTMLAnchorElement =>
          el instanceof HTMLAnchorElement && el.href === "blob:mock-url",
      );
    expect(anchors).toHaveLength(1);
    expect(anchors[0]?.download).toBe("report.pdf");
  });

  it("shows a spinner and disables the button while downloading", async () => {
    let resolveUrl!: (response: DownloadDocumentResponse) => void;
    apiMock.api.downloadDocument.mockReturnValue(
      new Promise<DownloadDocumentResponse>((resolve) => {
        resolveUrl = resolve;
      }),
    );
    const clickSpy = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => {});

    render(<DownloadButton documentId="doc-1" filename="report.pdf" />);
    fireEvent.click(screen.getByRole("button", { name: "Download report.pdf" }));

    // In flight — the button is disabled until the download completes.
    await waitFor(() =>
      expect(
        (
          screen.getByRole("button", {
            name: "Download report.pdf",
          }) as HTMLButtonElement
        ).disabled,
      ).toBe(true),
    );

    await act(async () => {
      resolveUrl(DOWNLOAD_RESPONSE);
    });

    await waitFor(() => expect(clickSpy).toHaveBeenCalledTimes(1));
    expect(
      (
        screen.getByRole("button", {
          name: "Download report.pdf",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(false);
  });

  it("shows an error when the presigned URL request fails", async () => {
    apiMock.api.downloadDocument.mockRejectedValue(
      new Error("Document not found"),
    );

    render(<DownloadButton documentId="doc-1" filename="report.pdf" />);
    fireEvent.click(screen.getByRole("button", { name: "Download report.pdf" }));

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Document not found");
    // No download attempt should have happened.
    expect(urlApi.createObjectURL).not.toHaveBeenCalled();
  });

  it("shows an error when fetching the file bytes fails", async () => {
    apiMock.api.downloadDocument.mockResolvedValue(DOWNLOAD_RESPONSE);
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        ({ ok: false, status: 403 } as unknown as Response),
      ),
    );

    render(<DownloadButton documentId="doc-1" filename="report.pdf" />);
    fireEvent.click(screen.getByRole("button", { name: "Download report.pdf" }));

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("status 403");
    expect(urlApi.createObjectURL).not.toHaveBeenCalled();
  });

  it("does nothing when disabled", () => {
    render(
      <DownloadButton documentId="doc-1" filename="report.pdf" disabled />,
    );

    const button = screen.getByRole("button", {
      name: "Download report.pdf",
    }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);

    fireEvent.click(button);
    expect(apiMock.api.downloadDocument).not.toHaveBeenCalled();
  });
});
