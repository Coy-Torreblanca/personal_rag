// ---------------------------------------------------------------------------
// Unit tests for `src/lib/api/upload.ts`.
//
// The API client (`@/lib/api/client`) and the browser `XMLHttpRequest` are
// mocked so the upload pipeline can be exercised deterministically without
// any network, R2, or backend dependency.
//
// Coverage targets:
//   - `toErrorMessage`            — every throwable shape
//   - `resolveUploadContext`      — env resolution + caching + failure modes
//   - `processUploadedDocument`   — retry/backoff + 400 classification
//   - `uploadFileToR2`            — full pipeline incl. XHR failure modes
// ---------------------------------------------------------------------------

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type {
  ProcessDocumentResponse,
  UploadUrlResponse,
} from "@/lib/api/types";
import type { UploadOptions, UploadResult } from "@/lib/api/upload";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

// `vi.hoisted` runs before the imports below, so the mocked client module can
// hand back the *same* `api` object and `ApiError` class the tests use. The
// `instanceof` checks inside `processUploadedDocument` only work because the
// class identity is shared between the SUT and the tests.
const { api, ApiError } = vi.hoisted(() => {
  class ApiError extends Error {
    constructor(
      public readonly status: number,
      message: string,
      public readonly body: unknown = null,
    ) {
      super(message);
      this.name = "ApiError";
    }
  }
  return {
    api: {
      getUploadUrl: vi.fn(),
      processDocument: vi.fn(),
    },
    ApiError,
  };
});

vi.mock("@/lib/api/client", () => ({ api, ApiError }));

// Controllable stand-in for the browser's XMLHttpRequest. Tests drive it via
// the `emit*` helpers instead of real network I/O.
class FakeXHR {
  static instances: FakeXHR[] = [];

  static reset() {
    FakeXHR.instances = [];
  }

  method = "";
  url = "";
  status = 0;
  timeout = 0;
  requestHeaders: Record<string, string> = {};
  sentBody: unknown = null;
  upload: {
    onprogress:
      | ((event: { lengthComputable: boolean; loaded: number; total: number }) => void)
      | null;
  } = { onprogress: null };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  ontimeout: (() => void) | null = null;
  onabort: (() => void) | null = null;

  open(method: string, url: string) {
    this.method = method;
    this.url = url;
  }

  setRequestHeader(name: string, value: string) {
    this.requestHeaders[name] = value;
  }

  send(body: unknown) {
    this.sentBody = body;
    FakeXHR.instances.push(this);
  }

  // --- Test drivers -----------------------------------------------------

  emitProgress(loaded: number, total: number) {
    this.upload.onprogress?.({ lengthComputable: true, loaded, total });
  }

  succeed(status = 200) {
    this.status = status;
    this.onload?.();
  }

  networkError() {
    this.onerror?.();
  }

  timeoutError() {
    this.ontimeout?.();
  }

  abort() {
    this.onabort?.();
  }
}

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const UPLOAD_URL_RESPONSE: UploadUrlResponse = {
  success: true,
  url: "https://test-bucket.r2.dev/org-1/report.pdf?sig=abc",
  bucket: "test-bucket",
  key: "org-1/report.pdf",
  method: "PUT",
  expires_in: 3600,
  message: "Presigned URL generated",
  job_id: "job-1",
};

const PROCESS_RESPONSE: ProcessDocumentResponse = {
  message: "Document processing started",
  document_id: "doc-1",
  task_id: "job-1",
  status: "processing",
};

function makePdfFile(type = "application/pdf"): File {
  return new File(["hello world"], "report.pdf", { type });
}

/** Re-import the module with a fresh module registry (resets `cachedContext`). */
async function loadFreshUploadModule() {
  vi.resetModules();
  return import("@/lib/api/upload");
}

// ---------------------------------------------------------------------------
// Setup / teardown
// ---------------------------------------------------------------------------

beforeEach(() => {
  FakeXHR.reset();
  // `resetAllMocks` (not just `clearAllMocks`) also wipes implementations:
  // a `mockResolvedValue`/`mockRejectedValue` from a previous test must
  // never leak into the next one (that caused an undriven-XHR hang when the
  // dev shell has NEXT_PUBLIC_* set).
  vi.resetAllMocks();
  vi.stubGlobal("XMLHttpRequest", FakeXHR);
  vi.stubEnv("NEXT_PUBLIC_ORGANIZATION_ID", "org-1");
  vi.stubEnv("NEXT_PUBLIC_USER_ID", "user-1");
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

// ---------------------------------------------------------------------------
// toErrorMessage
// ---------------------------------------------------------------------------

describe("toErrorMessage", () => {
  it("returns the message of an Error instance", async () => {
    const { toErrorMessage } = await loadFreshUploadModule();
    expect(toErrorMessage(new Error("boom"))).toBe("boom");
  });

  it("returns the message of an ApiError (a subclass of Error)", async () => {
    const { toErrorMessage } = await loadFreshUploadModule();
    expect(toErrorMessage(new ApiError(404, "not found"))).toBe("not found");
  });

  it("returns plain string throws as-is", async () => {
    const { toErrorMessage } = await loadFreshUploadModule();
    expect(toErrorMessage("string failure")).toBe("string failure");
  });

  it("returns the message of a structured error object", async () => {
    const { toErrorMessage } = await loadFreshUploadModule();
    expect(toErrorMessage({ message: "structured failure" })).toBe(
      "structured failure",
    );
  });

  it("falls back to a generic message for anything else", async () => {
    const { toErrorMessage } = await loadFreshUploadModule();
    expect(toErrorMessage(null)).toBe("An unexpected error occurred");
    expect(toErrorMessage(undefined)).toBe("An unexpected error occurred");
    expect(toErrorMessage(42)).toBe("An unexpected error occurred");
    expect(toErrorMessage({})).toBe("An unexpected error occurred");
    expect(toErrorMessage("   ")).toBe("An unexpected error occurred");
  });
});

// ---------------------------------------------------------------------------
// resolveUploadContext
// ---------------------------------------------------------------------------

describe("resolveUploadContext", () => {
  it("returns the organization and user from the environment", async () => {
    const { resolveUploadContext } = await loadFreshUploadModule();
    const context = await resolveUploadContext();
    expect(context).toEqual({ organizationId: "org-1", userId: "user-1" });
  });

  it("caches the resolved context (env changes after first call are ignored)", async () => {
    const { resolveUploadContext } = await loadFreshUploadModule();
    const first = await resolveUploadContext();

    vi.stubEnv("NEXT_PUBLIC_ORGANIZATION_ID", "org-2");
    const second = await resolveUploadContext();

    // The module-level cache must win — repeated uploads shouldn't re-read.
    expect(second).toBe(first);
    expect(second.organizationId).toBe("org-1");
  });

  it("throws a clear error when the organization id is missing", async () => {
    vi.stubEnv("NEXT_PUBLIC_ORGANIZATION_ID", "");
    const { resolveUploadContext } = await loadFreshUploadModule();
    await expect(resolveUploadContext()).rejects.toThrow(
      /NEXT_PUBLIC_ORGANIZATION_ID/,
    );
  });

  it("throws a clear error when the user id is missing", async () => {
    vi.stubEnv("NEXT_PUBLIC_USER_ID", "");
    const { resolveUploadContext } = await loadFreshUploadModule();
    await expect(resolveUploadContext()).rejects.toThrow(
      /NEXT_PUBLIC_USER_ID/,
    );
  });

  it("throws when both ids are missing", async () => {
    vi.stubEnv("NEXT_PUBLIC_ORGANIZATION_ID", "");
    vi.stubEnv("NEXT_PUBLIC_USER_ID", "");
    const { resolveUploadContext } = await loadFreshUploadModule();
    await expect(resolveUploadContext()).rejects.toThrow(
      /NEXT_PUBLIC_ORGANIZATION_ID and NEXT_PUBLIC_USER_ID/,
    );
  });
});

// ---------------------------------------------------------------------------
// processUploadedDocument
// ---------------------------------------------------------------------------

describe("processUploadedDocument", () => {
  it("returns the response when dispatch succeeds on the first attempt", async () => {
    vi.mocked(api.processDocument).mockResolvedValue(PROCESS_RESPONSE);
    const { processUploadedDocument } = await loadFreshUploadModule();

    const outcome = await processUploadedDocument("job-1");

    expect(outcome).toEqual({ response: PROCESS_RESPONSE, error: null });
    expect(api.processDocument).toHaveBeenCalledTimes(1);
    expect(api.processDocument).toHaveBeenCalledWith("job-1");
  });

  it("treats an undefined response (204) as success", async () => {
    vi.mocked(api.processDocument).mockResolvedValue(undefined);
    const { processUploadedDocument } = await loadFreshUploadModule();

    const outcome = await processUploadedDocument("job-1");

    expect(outcome.error).toBeNull();
    expect(outcome.response).toBeNull();
  });

  it("bails out immediately on a non-retryable 4xx (job not found)", async () => {
    vi.mocked(api.processDocument).mockRejectedValue(
      new ApiError(
        404,
        "Job id provided does not correspond with any known jobs.",
      ),
    );
    const { processUploadedDocument } = await loadFreshUploadModule();

    const outcome = await processUploadedDocument("job-1");

    expect(outcome.response).toBeNull();
    expect(outcome.error).toContain("does not correspond");
    // Exactly one attempt — retrying a 404 is pointless.
    expect(api.processDocument).toHaveBeenCalledTimes(1);
  });

  it("treats a 400 'already processing' as success (idempotent retry)", async () => {
    // An earlier attempt may have dispatched the Celery task while its
    // response was lost; the backend then refuses with this 400.
    vi.mocked(api.processDocument).mockRejectedValue(
      new ApiError(400, "Document is already processing."),
    );
    const { processUploadedDocument } = await loadFreshUploadModule();

    const outcome = await processUploadedDocument("job-1");

    expect(outcome).toEqual({ response: null, error: null });
    expect(api.processDocument).toHaveBeenCalledTimes(1);
  });

  it("treats a 400 'job not pending' as success", async () => {
    vi.mocked(api.processDocument).mockRejectedValue(
      new ApiError(400, "Job is not in pending status: completed"),
    );
    const { processUploadedDocument } = await loadFreshUploadModule();

    const outcome = await processUploadedDocument("job-1");

    expect(outcome.error).toBeNull();
  });

  it("retries a 400 'file not uploaded' and reports the error after all attempts", async () => {
    vi.mocked(api.processDocument).mockRejectedValue(
      new ApiError(
        400,
        "The document file has not been uploaded yet. Please upload the file before processing.",
      ),
    );
    vi.useFakeTimers();
    const { processUploadedDocument } = await loadFreshUploadModule();

    const promise = processUploadedDocument("job-1");
    await vi.advanceTimersByTimeAsync(10_000);
    const outcome = await promise;

    expect(outcome.error).toContain("not been uploaded");
    // 3 attempts with backoff — the file may appear in R2 momentarily.
    expect(api.processDocument).toHaveBeenCalledTimes(3);
  });

  it("recovers when a 5xx failure is followed by success", async () => {
    vi.mocked(api.processDocument)
      .mockRejectedValueOnce(new ApiError(500, "boom"))
      .mockRejectedValueOnce(new ApiError(502, "bad gateway"))
      .mockResolvedValueOnce(PROCESS_RESPONSE);
    vi.useFakeTimers();
    const { processUploadedDocument } = await loadFreshUploadModule();

    const promise = processUploadedDocument("job-1");
    await vi.advanceTimersByTimeAsync(10_000);
    const outcome = await promise;

    expect(outcome).toEqual({ response: PROCESS_RESPONSE, error: null });
    expect(api.processDocument).toHaveBeenCalledTimes(3);
  });

  it("reports the last error after exhausting all retries on persistent 5xx", async () => {
    vi.mocked(api.processDocument).mockRejectedValue(
      new ApiError(500, "internal server error"),
    );
    vi.useFakeTimers();
    const { processUploadedDocument } = await loadFreshUploadModule();

    const promise = processUploadedDocument("job-1");
    await vi.advanceTimersByTimeAsync(10_000);
    const outcome = await promise;

    expect(outcome.response).toBeNull();
    expect(outcome.error).toContain("internal server error");
    expect(api.processDocument).toHaveBeenCalledTimes(3);
  });
});

// ---------------------------------------------------------------------------
// uploadFileToR2
// ---------------------------------------------------------------------------

describe("uploadFileToR2", () => {
  type UploadFn = (
    file: File,
    options?: UploadOptions,
  ) => Promise<UploadResult>;

  /**
   * Start an upload with a given module instance and drive its PUT to a
   * successful 2xx response. The upload function is passed in because the
   * module is re-imported per test (fresh `cachedContext`).
   */
  async function uploadToCompletion(
    uploadFn: UploadFn,
    file: File,
    options?: UploadOptions,
  ): Promise<UploadResult> {
    const promise = uploadFn(file, options);
    await vi.waitFor(() => expect(FakeXHR.instances.length).toBe(1));
    FakeXHR.instances[0].succeed();
    return promise;
  }

  it("uploads the file to R2 and dispatches processing", async () => {
    vi.mocked(api.getUploadUrl).mockResolvedValue(UPLOAD_URL_RESPONSE);
    vi.mocked(api.processDocument).mockResolvedValue(PROCESS_RESPONSE);
    const { uploadFileToR2 } = await loadFreshUploadModule();

    const result = await uploadToCompletion(uploadFileToR2, makePdfFile());

    // Phase 2 — presigned URL minted with the resolved context + content type.
    expect(api.getUploadUrl).toHaveBeenCalledWith("report.pdf", {
      organizationId: "org-1",
      userId: "user-1",
      contentType: "application/pdf",
    });

    // Phase 3 — the PUT went to the presigned URL with matching headers and
    // the file as the body; the client-side timeout guard is armed.
    const xhr = FakeXHR.instances[0];
    expect(xhr).toBeDefined();
    expect(xhr.method).toBe("PUT");
    expect(xhr.url).toBe(UPLOAD_URL_RESPONSE.url);
    expect(xhr.requestHeaders["Content-Type"]).toBe("application/pdf");
    expect(xhr.sentBody).toBeInstanceOf(File);
    expect(xhr.timeout).toBe(5 * 60_000);

    // Phase 4 — processing dispatched with the job id from the URL response.
    expect(api.processDocument).toHaveBeenCalledWith("job-1");
    expect(result.uploadUrl).toBe(UPLOAD_URL_RESPONSE);
    expect(result.process).toEqual({ response: PROCESS_RESPONSE, error: null });
  });

  it("reports live progress percentages via the onProgress callback", async () => {
    vi.mocked(api.getUploadUrl).mockResolvedValue(UPLOAD_URL_RESPONSE);
    vi.mocked(api.processDocument).mockResolvedValue(PROCESS_RESPONSE);
    const { uploadFileToR2 } = await loadFreshUploadModule();
    const onProgress = vi.fn();

    const promise = uploadFileToR2(makePdfFile(), { onProgress });
    // Let the async chain reach the XHR construction.
    await vi.waitFor(() => expect(FakeXHR.instances.length).toBe(1));

    FakeXHR.instances[0].emitProgress(25, 100);
    FakeXHR.instances[0].emitProgress(75, 100);
    FakeXHR.instances[0].succeed();
    await promise;

    expect(onProgress).toHaveBeenCalledWith({ loaded: 25, total: 100, percent: 25 });
    expect(onProgress).toHaveBeenCalledWith({ loaded: 75, total: 100, percent: 75 });
  });

  it("falls back to application/octet-stream when the file has no type", async () => {
    vi.mocked(api.getUploadUrl).mockResolvedValue(UPLOAD_URL_RESPONSE);
    const { uploadFileToR2 } = await loadFreshUploadModule();

    await uploadToCompletion(uploadFileToR2, makePdfFile(""), {
      autoProcess: false,
    });

    expect(api.getUploadUrl).toHaveBeenCalledWith(
      "report.pdf",
      expect.objectContaining({ contentType: "application/octet-stream" }),
    );
    expect(FakeXHR.instances[0].requestHeaders["Content-Type"]).toBe(
      "application/octet-stream",
    );
  });

  it("skips processing dispatch when autoProcess is false", async () => {
    vi.mocked(api.getUploadUrl).mockResolvedValue(UPLOAD_URL_RESPONSE);
    const { uploadFileToR2 } = await loadFreshUploadModule();

    const result = await uploadToCompletion(uploadFileToR2, makePdfFile(), {
      autoProcess: false,
    });

    expect(api.processDocument).not.toHaveBeenCalled();
    expect(result.process).toEqual({ response: null, error: null });
  });

  it("captures a failed processing dispatch instead of throwing", async () => {
    vi.mocked(api.getUploadUrl).mockResolvedValue(UPLOAD_URL_RESPONSE);
    vi.mocked(api.processDocument).mockRejectedValue(
      new ApiError(500, "internal server error"),
    );
    vi.useFakeTimers();
    const { uploadFileToR2 } = await loadFreshUploadModule();

    const promise = uploadFileToR2(makePdfFile());
    // The PUT completes immediately (no timers involved); only the dispatch
    // retries need the fake clock to advance.
    await vi.waitFor(() => expect(FakeXHR.instances.length).toBe(1));
    FakeXHR.instances[0].succeed();
    await vi.advanceTimersByTimeAsync(10_000);
    const result = await promise;

    // The file *was* uploaded — the failure is reported, not thrown.
    expect(result.process.error).toContain("internal server error");
    expect(result.process.response).toBeNull();
  });

  it("throws when the environment variables are missing", async () => {
    // Stub to empty strings instead of calling `unstubAllEnvs()`: the
    // developer's real shell may legitimately have NEXT_PUBLIC_* set (e.g.
    // from docker-compose), and restoring them would send this test down
    // the full upload path. Empty stubs make the failure deterministic.
    vi.stubEnv("NEXT_PUBLIC_ORGANIZATION_ID", "");
    vi.stubEnv("NEXT_PUBLIC_USER_ID", "");
    const { uploadFileToR2 } = await loadFreshUploadModule();

    await expect(uploadFileToR2(makePdfFile())).rejects.toThrow(
      /NEXT_PUBLIC_ORGANIZATION_ID/,
    );
    expect(api.getUploadUrl).not.toHaveBeenCalled();
  });

  it("throws when the API does not return an upload URL", async () => {
    vi.mocked(api.getUploadUrl).mockResolvedValue(undefined);
    const { uploadFileToR2 } = await loadFreshUploadModule();

    await expect(uploadFileToR2(makePdfFile())).rejects.toThrow(
      /did not return an upload URL/,
    );
    expect(FakeXHR.instances.length).toBe(0);
  });

  it("rejects when R2 answers with a non-2xx status", async () => {
    vi.mocked(api.getUploadUrl).mockResolvedValue(UPLOAD_URL_RESPONSE);
    const { uploadFileToR2 } = await loadFreshUploadModule();

    const promise = uploadFileToR2(makePdfFile());
    await vi.waitFor(() => expect(FakeXHR.instances.length).toBe(1));
    FakeXHR.instances[0].succeed(403);

    await expect(promise).rejects.toThrow(/status 403/);
    // Processing must NOT be dispatched for a file that never made it to R2.
    expect(api.processDocument).not.toHaveBeenCalled();
  });

  it("rejects with a network error message when the PUT fails", async () => {
    vi.mocked(api.getUploadUrl).mockResolvedValue(UPLOAD_URL_RESPONSE);
    const { uploadFileToR2 } = await loadFreshUploadModule();

    const promise = uploadFileToR2(makePdfFile());
    await vi.waitFor(() => expect(FakeXHR.instances.length).toBe(1));
    FakeXHR.instances[0].networkError();

    await expect(promise).rejects.toThrow(/network error/);
  });

  it("rejects with a timeout message when the PUT hangs", async () => {
    vi.mocked(api.getUploadUrl).mockResolvedValue(UPLOAD_URL_RESPONSE);
    const { uploadFileToR2 } = await loadFreshUploadModule();

    const promise = uploadFileToR2(makePdfFile());
    await vi.waitFor(() => expect(FakeXHR.instances.length).toBe(1));
    FakeXHR.instances[0].timeoutError();

    await expect(promise).rejects.toThrow(/timed out after 300s/);
  });

  it("rejects with an abort message when the PUT is aborted", async () => {
    vi.mocked(api.getUploadUrl).mockResolvedValue(UPLOAD_URL_RESPONSE);
    const { uploadFileToR2 } = await loadFreshUploadModule();

    const promise = uploadFileToR2(makePdfFile());
    await vi.waitFor(() => expect(FakeXHR.instances.length).toBe(1));
    FakeXHR.instances[0].abort();

    await expect(promise).rejects.toThrow(/aborted/);
  });
});
