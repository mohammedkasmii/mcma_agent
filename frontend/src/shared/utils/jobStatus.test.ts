import { describe, expect, it } from "vitest";
import { JOB_STATUSES } from "@shared/types";
import {
  canAuthorizeExecution,
  isDryRunBlocked,
  isJobInFlight,
  jobStatusLabel,
  jobStatusTone,
} from "./jobStatus";

describe("job status mapping", () => {
  it("labels every status the backend can store", () => {
    for (const status of JOB_STATUSES) {
      expect(jobStatusLabel(status).length).toBeGreaterThan(0);
      expect(jobStatusTone(status).length).toBeGreaterThan(0);
    }
  });

  it("covers the nineteen statuses of the backend CHECK constraint", () => {
    expect(JOB_STATUSES).toHaveLength(19);
  });
});

describe("in-flight classification", () => {
  it("treats the dry-run working states as in flight", () => {
    for (const status of ["QUEUED", "PLANNING", "PLANNED", "READ_ONLY_IDENTITY_CHECK"] as const) {
      expect(isJobInFlight(status)).toBe(true);
    }
  });

  it("treats decision and failure states as settled", () => {
    for (const status of [
      "DRY_RUN_VERIFIED",
      "NEEDS_REVIEW",
      "IDENTITY_FAILED",
      "WRITE_ABORTED",
      "READY_FOR_HUMAN_REVIEW",
      "HUMAN_CONFIRMED_COMPLETE",
      "ERROR",
    ] as const) {
      expect(isJobInFlight(status)).toBe(false);
    }
  });
});

describe("execution authorization gate", () => {
  it("allows only a verified dry-run", () => {
    expect(canAuthorizeExecution("DRY_RUN_VERIFIED")).toBe(true);
    for (const status of JOB_STATUSES.filter((s) => s !== "DRY_RUN_VERIFIED")) {
      expect(canAuthorizeExecution(status)).toBe(false);
    }
  });

  it("blocks absolutely on NEEDS_REVIEW and IDENTITY_FAILED", () => {
    expect(isDryRunBlocked("NEEDS_REVIEW")).toBe(true);
    expect(isDryRunBlocked("IDENTITY_FAILED")).toBe(true);
    expect(canAuthorizeExecution("NEEDS_REVIEW")).toBe(false);
    expect(canAuthorizeExecution("IDENTITY_FAILED")).toBe(false);
  });
});
