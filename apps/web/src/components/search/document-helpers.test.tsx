// @vitest-environment jsdom
// ---------------------------------------------------------------------------
// Unit tests for the shared document rendering helpers
// (``document-helpers.tsx``). These are pure functions with no component
// tree, so they are tested directly without rendering.
// ---------------------------------------------------------------------------

import { describe, expect, it } from "vitest";
import { DocumentStatus } from "@/lib/api/types";
import {
  formatFileSize,
  relevanceColor,
  statusColor,
  statusLabel,
  truncateFilename,
} from "./document-helpers";

// ---------------------------------------------------------------------------
// truncateFilename
// ---------------------------------------------------------------------------

describe("truncateFilename", () => {
  it("leaves names at or under the limit unchanged", () => {
    expect(truncateFilename("report.pdf")).toBe("report.pdf");
    expect(truncateFilename("a".repeat(48))).toBe("a".repeat(48));
  });

  it("truncates long names while preserving the extension", () => {
    const name = "my-very-long-report-name-2026-q3-final-version.pdf";
    const result = truncateFilename(name, 48);
    expect(result.length).toBeLessThanOrEqual(48);
    expect(result.endsWith(".pdf")).toBe(true);
    expect(result).toContain("…");
  });

  it("truncates names without an extension", () => {
    const name = "a".repeat(60);
    const result = truncateFilename(name, 48);
    // ``max - 3`` characters plus the ellipsis.
    expect(result.length).toBe(46);
    expect(result).toBe("a".repeat(45) + "…");
    expect(result.endsWith("…")).toBe(true);
  });

  it("keeps the result deterministic when max is smaller than the extension", () => {
    // The extension is the final dot suffix (``.gz`` here) and alone
    // exceeds ``max`` — the output must stay shorter than the input with
    // the ellipsis + extension intact rather than misplacing the
    // ellipsis or returning a string longer than ``max``.
    const name = "archive.tar.gz";
    const result = truncateFilename(name, 5);
    expect(result).toBe("….gz");
    expect(result.length).toBeLessThan(name.length);
    expect(result.endsWith(".gz")).toBe(true);
    expect(result).toContain("…");
  });

  it("respects a custom max length", () => {
    const name = "quarterly-report-final-2026.pdf";
    const result = truncateFilename(name, 20);
    expect(result.length).toBeLessThanOrEqual(20);
    expect(result.endsWith(".pdf")).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// formatFileSize
// ---------------------------------------------------------------------------

describe("formatFileSize", () => {
  it("formats bytes, KB, and MB", () => {
    expect(formatFileSize(512)).toBe("512 B");
    expect(formatFileSize(1024)).toBe("1.0 KB");
    expect(formatFileSize(2048)).toBe("2.0 KB");
    expect(formatFileSize(3 * 1024 * 1024)).toBe("3.0 MB");
  });

  it("returns an empty string for null or undefined sizes", () => {
    expect(formatFileSize(null)).toBe("");
    expect(formatFileSize(undefined)).toBe("");
  });
});

// ---------------------------------------------------------------------------
// statusLabel / statusColor
// ---------------------------------------------------------------------------

describe("statusLabel", () => {
  it("maps every known status to a human-readable label", () => {
    expect(statusLabel(DocumentStatus.UPLOADING)).toBe("Uploading…");
    expect(statusLabel(DocumentStatus.UPLOADED)).toBe("Uploaded");
    expect(statusLabel(DocumentStatus.PROCESSING)).toBe("Processing…");
    expect(statusLabel(DocumentStatus.PROCESSED)).toBe("Ready");
    expect(statusLabel(DocumentStatus.ERROR)).toBe("Error");
  });

  it("falls back to the raw status string for unknown values", () => {
    // The API may introduce statuses before this switch is updated.
    expect(statusLabel("archived" as DocumentStatus)).toBe("archived");
  });
});

describe("statusColor", () => {
  it("colors ready green, error red, and in-flight amber", () => {
    expect(statusColor(DocumentStatus.PROCESSED)).toContain("text-emerald");
    expect(statusColor(DocumentStatus.ERROR)).toContain("text-red");
    expect(statusColor(DocumentStatus.PROCESSING)).toContain("text-amber");
    expect(statusColor(DocumentStatus.UPLOADING)).toContain("text-amber");
  });
});

// ---------------------------------------------------------------------------
// relevanceColor
// ---------------------------------------------------------------------------

describe("relevanceColor", () => {
  it("tiers scores into high / medium / low colors", () => {
    expect(relevanceColor(0.9)).toContain("text-emerald");
    expect(relevanceColor(0.5)).toContain("text-amber");
    expect(relevanceColor(0.1)).toContain("text-muted-foreground");
  });

  it("treats boundary scores as the upper tier", () => {
    expect(relevanceColor(0.7)).toContain("text-emerald");
    expect(relevanceColor(0.4)).toContain("text-amber");
  });
});
