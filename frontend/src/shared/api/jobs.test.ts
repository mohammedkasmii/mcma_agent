import { describe, expect, it } from "vitest";
import { createDryRun, createExecution, fetchJob, fetchJobPlan, jobPath } from "./jobs";
import { ApiRequestError } from "./client";
import { clearCookies, mockJsonResponse, setCsrfCookie } from "../../test/apiMock";
import {
  DRY_RUN_JOB_WIRE,
  PLAN_WIRE,
  SYNTHETIC_DOSSIER,
  WRITABLE_ACCOUNT_WIRE,
} from "../../test/fixtures";

const ACCOUNT_ID = WRITABLE_ACCOUNT_WIRE.account_id;

function sentBody(stub: { mock: { calls: unknown[][] } }): Record<string, unknown> {
  const init = stub.mock.calls[0]?.[1] as RequestInit;
  return JSON.parse(init.body as string) as Record<string, unknown>;
}

describe("fetchJob", () => {
  it("asks for one job by id", async () => {
    const stub = mockJsonResponse({ jobs: [DRY_RUN_JOB_WIRE] });
    await fetchJob("test-job-dry-1", ACCOUNT_ID);
    expect(stub.mock.calls[0]?.[0]).toBe(jobPath("test-job-dry-1"));
    expect((stub.mock.calls[0]?.[1] as RequestInit).method).toBe("GET");
  });

  it("returns null for a job the backend did not return", async () => {
    mockJsonResponse({ jobs: [] });
    await expect(fetchJob("missing", ACCOUNT_ID)).resolves.toBeNull();
  });

  it("fails closed for a job belonging to another account", async () => {
    mockJsonResponse({ jobs: [{ ...DRY_RUN_JOB_WIRE, account_id: "test-account-readonly" }] });
    await expect(fetchJob("test-job-dry-1", ACCOUNT_ID)).rejects.toThrow(ApiRequestError);
  });
});

describe("fetchJobPlan", () => {
  it("reads the plan of one job", async () => {
    const stub = mockJsonResponse(PLAN_WIRE);
    const plan = await fetchJobPlan("test-job-dry-1");
    expect(stub.mock.calls[0]?.[0]).toBe("/jobs/test-job-dry-1/plan");
    expect(plan.steps[0]?.ht).toBe("1200.50");
  });
});

describe("createDryRun", () => {
  it("sends exactly the three fields the endpoint accepts", async () => {
    setCsrfCookie();
    const stub = mockJsonResponse({ job_id: "test-job-dry-1", status: "QUEUED" });

    await createDryRun({
      accountId: ACCOUNT_ID,
      typedInput: SYNTHETIC_DOSSIER,
      idempotencyKey: "key-under-test",
    });

    const [path, init] = stub.mock.calls[0] as [string, RequestInit];
    expect(path).toBe("/jobs/dry-runs");
    expect(init.method).toBe("POST");
    expect(sentBody(stub)).toEqual({
      account_id: ACCOUNT_ID,
      typed_input: SYNTHETIC_DOSSIER,
      idempotency_key: "key-under-test",
    });
  });

  it("never sends the server-owned fields", async () => {
    setCsrfCookie();
    const stub = mockJsonResponse({ job_id: "test-job-dry-1", status: "QUEUED" });

    await createDryRun({ accountId: ACCOUNT_ID, typedInput: {}, idempotencyKey: "k" });

    const body = sentBody(stub);
    expect(body).not.toHaveProperty("workflow_name");
    expect(body).not.toHaveProperty("mode");
    expect(body).not.toHaveProperty("user_id");
  });

  it("carries credentials and the CSRF header", async () => {
    setCsrfCookie("token-under-test");
    const stub = mockJsonResponse({ job_id: "j", status: "QUEUED" });

    await createDryRun({ accountId: ACCOUNT_ID, typedInput: {}, idempotencyKey: "k" });

    const init = stub.mock.calls[0]?.[1] as RequestInit;
    expect(init.credentials).toBe("include");
    expect((init.headers as Record<string, string>)["X-CSRF-Token"]).toBe("token-under-test");
  });

  it("does not reach the network without a CSRF cookie", async () => {
    clearCookies();
    const stub = mockJsonResponse({});
    await expect(
      createDryRun({ accountId: ACCOUNT_ID, typedInput: {}, idempotencyKey: "k" }),
    ).rejects.toThrow(ApiRequestError);
    expect(stub).not.toHaveBeenCalled();
  });
});

describe("createExecution", () => {
  it("posts to the parent dry-run's executions endpoint", async () => {
    setCsrfCookie();
    const stub = mockJsonResponse({ job_id: "test-job-exec-1", status: "QUEUED" });

    const created = await createExecution("test-job-dry-1", "key-under-test");

    expect(stub.mock.calls[0]?.[0]).toBe("/jobs/test-job-dry-1/executions");
    expect((stub.mock.calls[0]?.[1] as RequestInit).method).toBe("POST");
    // A different job from its parent.
    expect(created.jobId).toBe("test-job-exec-1");
    expect(created.jobId).not.toBe("test-job-dry-1");
  });

  it("sends only an idempotency key", async () => {
    setCsrfCookie();
    const stub = mockJsonResponse({ job_id: "test-job-exec-1", status: "QUEUED" });

    await createExecution("test-job-dry-1", "key-under-test");

    const body = sentBody(stub);
    expect(body).toEqual({ idempotency_key: "key-under-test" });
    // The account comes from the parent job, server-side; mode and workflow
    // are not client-settable at all.
    expect(body).not.toHaveProperty("account_id");
    expect(body).not.toHaveProperty("mode");
    expect(body).not.toHaveProperty("workflow_name");
    expect(body).not.toHaveProperty("user_id");
  });
});
