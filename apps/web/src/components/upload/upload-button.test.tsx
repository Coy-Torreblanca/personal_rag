// @vitest-environment jsdom
// ---------------------------------------------------------------------------
// Component tests for `UploadButton`.
//
// The upload pipeline (`@/lib/api/upload`) and the UI `Button` are mocked so
// the component's state machine can be tested in isolation:
//
//   idle → uploading (progress%) → success | partial | error
//                                  └───────────────┘──▶ Retry → success
//
// The partial-banner assertion doubles as a regression test for the JSX
// whitespace bug (the space between the colon and the message must render).
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
import { UploadButton } from "./upload-button";
import type { UploadProgress, UploadResult } from "@/lib/api/upload";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const uploadApi = vi.hoisted(() => ({
  processUploadedDocument: vi.fn(),
  toErrorMessage: vi.fn(
    (err: unknown) =>
      err instanceof Error ? err.message : "An unexpected error occurred",
  ),
  uploadFileToR2: vi.fn(),
}));

vi.mock("@/lib/api/upload", () => uploadApi);

// Replace the headless base-ui Button with a plain <button> so the test
// doesn't depend on the UI library's DOM behaviour. `variant`/`size` are
// dropped (the real Button uses them only for styling).
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
    // The real Button consumes `variant`/`size` for styling; the plain test
    // button ignores them (marked used to satisfy no-unused-vars).
    void variant;
    void size;
    return <button {...props}>{children}</button>;
  },
}));

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const SUCCESS_RESULT: UploadResult = {
  uploadUrl: {
    success: true,
    url: "https://test-bucket.r2.dev/org-1/report.pdf?sig=abc",
    bucket: "test-bucket",
    key: "org-1/report.pdf",
    method: "PUT",
    expires_in: 3600,
    message: "Presigned URL generated",
    job_id: "job-1",
  },
  process: {
    response: {
      message: "Document processing started",
      document_id: "doc-1",
      task_id: "job-1",
      status: "processing",
    },
    error: null,
  },
};

const PARTIAL_RESULT: UploadResult = {
  ...SUCCESS_RESULT,
  process: { response: null, error: "Dispatch failed: internal server error" },
};

function selectFile(
  container: HTMLElement,
  name = "report.pdf",
  type = "application/pdf",
) {
  const input = container.querySelector('input[type="file"]');
  if (!input) throw new Error("file input not found");
  fireEvent.change(input, {
    target: { files: [new File(["hello world"], name, { type })] },
  });
}

// ---------------------------------------------------------------------------
// Setup / teardown
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.clearAllMocks();
  // Every test sets its own behaviour for these two functions, so wipe
  // implementations from previous tests too — a leaked `mockResolvedValue`
  // would send a test down the wrong state path. `toErrorMessage` is
  // intentionally left intact: its implementation is defined once in the
  // hoisted mock factory and shared by all tests.
  uploadApi.uploadFileToR2.mockReset();
  uploadApi.processUploadedDocument.mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
  // RTL only auto-registers cleanup when vitest globals are enabled; we keep
  // globals off, so unmount the previous tree explicitly to avoid DOM leaks
  // between tests ("Found multiple elements..." failures).
  cleanup();
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("UploadButton", () => {
  it("renders the Upload button and opens the file picker on click", () => {
    render(<UploadButton />);

    const button = screen.getByRole("button", { name: "Upload" });
    expect(button).toBeTruthy();

    const clickSpy = vi
      .spyOn(HTMLInputElement.prototype, "click")
      .mockImplementation(() => {});
    fireEvent.click(button);
    expect(clickSpy).toHaveBeenCalledTimes(1);
  });

  it("shows live progress while uploading and disables the button", async () => {
    uploadApi.uploadFileToR2.mockImplementation(
      async (
        _file: File,
        options?: { onProgress?: (p: UploadProgress) => void },
      ) => {
        options?.onProgress?.({ loaded: 50, total: 100, percent: 50 });
        // Hold the "uploading" state briefly so the disabled assertion below
        // runs against a stable intermediate render (like a real upload).
        await new Promise((resolve) => setTimeout(resolve, 50));
        return SUCCESS_RESULT;
      },
    );

    const { container } = render(<UploadButton />);
    selectFile(container);

    // Progress label rendered from the streamed progress callback...
    expect(await screen.findByText(/Uploading 50%/i)).toBeTruthy();
    // ...and the button is disabled while the upload is in flight.
    expect(
      (screen.getByRole("button", { name: /Uploading 50%/i }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);

    // Terminal state follows once the upload completes.
    expect(
      await screen.findByText(/report\.pdf uploaded — processing started/i),
    ).toBeTruthy();
    expect(uploadApi.uploadFileToR2).toHaveBeenCalledWith(
      expect.any(File),
      expect.objectContaining({ onProgress: expect.any(Function) }),
    );
  });

  it("shows a success banner and dismisses it", async () => {
    uploadApi.uploadFileToR2.mockResolvedValue(SUCCESS_RESULT);

    const { container } = render(<UploadButton />);
    selectFile(container);

    expect(
      await screen.findByText(/report\.pdf uploaded — processing started/i),
    ).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    await waitFor(() =>
      expect(
        screen.queryByText(/report\.pdf uploaded — processing started/i),
      ).toBeNull(),
    );
    // The button is usable again after dismissal.
    expect(screen.getByRole("button", { name: "Upload" })).toBeTruthy();
  });

  it("shows a partial banner with a Retry action when dispatch fails", async () => {
    uploadApi.uploadFileToR2.mockResolvedValue(PARTIAL_RESULT);
    uploadApi.processUploadedDocument.mockResolvedValue({
      response: SUCCESS_RESULT.process.response,
      error: null,
    });

    const { container } = render(<UploadButton />);
    selectFile(container);

    // Regression: the rendered text must contain a space after the colon
    // (JSX strips newlines adjacent to expressions, so it must be explicit).
    expect(
      await screen.findByText(/processing didn't start: Dispatch failed/i),
    ).toBeTruthy();

    // Retrying the dispatch flips the banner to success.
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(
      await screen.findByText(/report\.pdf uploaded — processing started/i),
    ).toBeTruthy();
    expect(uploadApi.processUploadedDocument).toHaveBeenCalledWith("job-1");
  });

  it("keeps the partial banner when the retry also fails", async () => {
    uploadApi.uploadFileToR2.mockResolvedValue(PARTIAL_RESULT);
    uploadApi.processUploadedDocument.mockResolvedValue({
      response: null,
      error: "still failing",
    });

    const { container } = render(<UploadButton />);
    selectFile(container);
    await screen.findByText(/processing didn't start: Dispatch failed/i);

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(
      await screen.findByText(/processing didn't start: still failing/i),
    ).toBeTruthy();
  });

  it("shows an error banner when the upload itself fails and dismisses it", async () => {
    uploadApi.uploadFileToR2.mockRejectedValue(
      new Error("Upload to R2 failed (status 403). Please try again."),
    );

    const { container } = render(<UploadButton />);
    selectFile(container);

    expect(await screen.findByText(/status 403/i)).toBeTruthy();
    // A failed upload must never dispatch processing.
    expect(uploadApi.processUploadedDocument).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    await waitFor(() =>
      expect(screen.queryByText(/status 403/i)).toBeNull(),
    );
  });

  it("keeps the button disabled for the whole duration of a slow upload", async () => {
    let resolveUpload!: (result: UploadResult) => void;
    uploadApi.uploadFileToR2.mockReturnValue(
      new Promise<UploadResult>((resolve) => {
        resolveUpload = resolve;
      }),
    );

    const { container } = render(<UploadButton />);
    selectFile(container);

    const uploadingButton = await screen.findByRole("button", {
      name: /Uploading/i,
    });
    expect((uploadingButton as HTMLButtonElement).disabled).toBe(true);

    // Resolve the pending upload — the button returns to normal.
    await act(async () => {
      resolveUpload(SUCCESS_RESULT);
    });
    expect(
      await screen.findByText(/report\.pdf uploaded — processing started/i),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "Upload" })).toBeTruthy();
  });

  it("ignores change events without a file", async () => {
    const { container } = render(<UploadButton />);
    const input = container.querySelector('input[type="file"]');
    if (!input) throw new Error("file input not found");

    fireEvent.change(input, { target: { files: [] } });

    expect(uploadApi.uploadFileToR2).not.toHaveBeenCalled();
  });
});
