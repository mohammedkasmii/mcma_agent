import { describe, expect, it } from "vitest";
import { toCreatedJobId, toJob, toJobById, toJobPlan } from "./jobs";
import { ApiRequestError } from "../client";
import {
  DRY_RUN_JOB_WIRE,
  EXECUTION_JOB_WIRE,
  PLAN_NEEDS_REVIEW_WIRE,
  PLAN_WIRE,
  READ_ONLY_ACCOUNT_WIRE,
  WRITABLE_ACCOUNT_WIRE,
} from "../../../test/fixtures";

const ACCOUNT_ID = WRITABLE_ACCOUNT_WIRE.account_id;

describe("toJob", () => {
  it("maps every wire field onto the frontend record", () => {
    expect(toJob(DRY_RUN_JOB_WIRE)).toEqual({
      jobId: "test-job-dry-1",
      accountId: ACCOUNT_ID,
      parentJobId: null,
      workflowName: "test_workflow",
      mode: "DRY_RUN",
      status: "DRY_RUN_VERIFIED",
      reasonCode: null,
      planHash: DRY_RUN_JOB_WIRE.plan_hash,
      createdAt: "2026-01-15T09:00:00Z",
      startedAt: "2026-01-15T09:00:05Z",
      finishedAt: "2026-01-15T09:01:00Z",
    });
  });

  it("leaves no snake_case key on the mapped record", () => {
    const mapped = toJob(DRY_RUN_JOB_WIRE) as unknown as Record<string, unknown>;
    for (const key of Object.keys(mapped)) {
      expect(key).not.toContain("_");
    }
  });

  it("preserves nullable timestamps truthfully", () => {
    const unstarted = toJob({ ...DRY_RUN_JOB_WIRE, started_at: null, finished_at: null });
    expect(unstarted.startedAt).toBeNull();
    expect(unstarted.finishedAt).toBeNull();
    expect(toJob(EXECUTION_JOB_WIRE).parentJobId).toBe("test-job-dry-1");
  });

  it("fails closed on an unknown status", () => {
    expect(() => toJob({ ...DRY_RUN_JOB_WIRE, status: "ALMOST_DONE" })).toThrow(ApiRequestError);
    expect(() => toJob({ ...DRY_RUN_JOB_WIRE, status: null })).toThrow(ApiRequestError);
  });

  it("fails closed on an unknown mode", () => {
    expect(() => toJob({ ...DRY_RUN_JOB_WIRE, mode: "PREVIEW" })).toThrow(ApiRequestError);
  });

  it("fails closed on a missing or mistyped field", () => {
    const { job_id: _dropped, ...incomplete } = DRY_RUN_JOB_WIRE;
    expect(() => toJob(incomplete)).toThrow(ApiRequestError);
    expect(() => toJob({ ...DRY_RUN_JOB_WIRE, account_id: 7 })).toThrow(ApiRequestError);
  });

  it("accepts every status the backend can store", () => {
    for (const status of [
      "QUEUED",
      "PLANNING",
      "NEEDS_REVIEW",
      "PLANNED",
      "READ_ONLY_IDENTITY_CHECK",
      "DRY_RUN_VERIFIED",
      "IDENTITY_FAILED",
      "WRITING",
      "READY_FOR_HUMAN_REVIEW",
      "ERROR",
    ]) {
      expect(toJob({ ...DRY_RUN_JOB_WIRE, status }).status).toBe(status);
    }
  });
});

describe("toJobById", () => {
  it("finds the requested job", () => {
    const job = toJobById({ jobs: [DRY_RUN_JOB_WIRE] }, "test-job-dry-1", ACCOUNT_ID);
    expect(job?.jobId).toBe("test-job-dry-1");
  });

  it("returns null when the backend did not return that job", () => {
    expect(toJobById({ jobs: [] }, "test-job-dry-1", ACCOUNT_ID)).toBeNull();
  });

  it("fails closed when the job belongs to another account", () => {
    expect(() =>
      toJobById(
        { jobs: [{ ...DRY_RUN_JOB_WIRE, account_id: READ_ONLY_ACCOUNT_WIRE.account_id }] },
        "test-job-dry-1",
        ACCOUNT_ID,
      ),
    ).toThrow(ApiRequestError);
  });

  it("fails closed on a malformed envelope", () => {
    expect(() => toJobById({}, "x", ACCOUNT_ID)).toThrow(ApiRequestError);
    expect(() => toJobById({ jobs: {} }, "x", ACCOUNT_ID)).toThrow(ApiRequestError);
    expect(() => toJobById(null, "x", ACCOUNT_ID)).toThrow(ApiRequestError);
  });
});

describe("toCreatedJobId", () => {
  it("reads the created job and its status", () => {
    expect(toCreatedJobId({ job_id: "test-job-exec-1", status: "QUEUED" })).toEqual({
      jobId: "test-job-exec-1",
      status: "QUEUED",
    });
  });

  it("fails closed on a malformed body", () => {
    expect(() => toCreatedJobId({ job_id: "x" })).toThrow(ApiRequestError);
    expect(() => toCreatedJobId({ job_id: "x", status: "NOPE" })).toThrow(ApiRequestError);
  });
});

describe("toJobPlan", () => {
  it("maps the display plan", () => {
    const plan = toJobPlan(PLAN_WIRE, DRY_RUN_JOB_WIRE.job_id);
    expect(plan.jobId).toBe("test-job-dry-1");
    expect(plan.repairWorkflow).toBe("MODE_NORMAL");
    expect(plan.steps).toHaveLength(2);
    expect(plan.fieldIntents).toHaveLength(2);
    expect(plan.needsReview).toEqual([]);
  });

  it("keeps decimal amounts as the exact strings the backend sent", () => {
    const plan = toJobPlan(PLAN_WIRE, DRY_RUN_JOB_WIRE.job_id);
    expect(plan.steps[0]?.ht).toBe("1200.50");
    expect(typeof plan.steps[0]?.ht).toBe("string");
    expect(plan.steps[1]?.vetuste).toBe("15.25");
    // Never round-tripped through a number: "1200.50" must not become 1200.5.
    expect(plan.steps[0]?.ht).not.toBe(String(Number("1200.50")));
  });

  it("maps needs_review entries including a null detail", () => {
    const plan = toJobPlan(PLAN_NEEDS_REVIEW_WIRE, DRY_RUN_JOB_WIRE.job_id);
    expect(plan.needsReview).toHaveLength(2);
    expect(plan.needsReview[1]?.detail).toBeNull();
  });

  it("does not read or invent an expected identity", () => {
    const plan = toJobPlan({ ...PLAN_WIRE, expected_identity: { matricule: "X" } }, DRY_RUN_JOB_WIRE.job_id);
    expect(Object.keys(plan)).not.toContain("expectedIdentity");
    expect(JSON.stringify(plan)).not.toContain("matricule");
  });

  it("fails closed when the plan names a different job", () => {
    // The plan an employee reviews must be the plan of the run they opened.
    expect(() => toJobPlan(PLAN_WIRE, "test-job-other")).toThrow(ApiRequestError);
    expect(() =>
      toJobPlan({ ...PLAN_WIRE, job_id: "test-job-other" }, DRY_RUN_JOB_WIRE.job_id),
    ).toThrow(ApiRequestError);
  });

  it("fails closed on a malformed plan", () => {
    expect(() => toJobPlan({ ...PLAN_WIRE, steps: "none" }, DRY_RUN_JOB_WIRE.job_id)).toThrow(ApiRequestError);
    expect(() => toJobPlan({ ...PLAN_WIRE, plan_hash: null }, DRY_RUN_JOB_WIRE.job_id)).toThrow(ApiRequestError);
    expect(() => toJobPlan({ ...PLAN_WIRE, steps: [{ rubrique_id: "x" }] }, DRY_RUN_JOB_WIRE.job_id)).toThrow(
      ApiRequestError,
    );
  });
});
