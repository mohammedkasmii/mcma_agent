import type { Job, JobPlan, JobStatus } from "@shared/types";
import { apiGet, apiSend } from "./client";
import { toCreatedJobId, toJobById, toJobPlan } from "./adapters/jobs";

/**
 * The automation-job endpoints.
 *
 * Three fields are server-owned and are never sent from here: `mode`,
 * `workflow_name` and — for executions — `account_id`. The backend rejects
 * the first two outright and derives the account from the parent dry-run.
 * Sending them would be inventing authority this frontend does not have.
 */

export const JOBS_PATH = "/jobs";

export function jobPath(jobId: string): string {
  const query = new URLSearchParams({ job_id: jobId });
  return `${JOBS_PATH}?${query.toString()}`;
}

export function jobPlanPath(jobId: string): string {
  return `${JOBS_PATH}/${encodeURIComponent(jobId)}/plan`;
}

/**
 * Reads one job, cross-checked against the account whose workspace is open.
 * Returns null when the backend does not return that job at all.
 */
export async function fetchJob(
  jobId: string,
  expectedAccountId: string,
  signal?: AbortSignal,
): Promise<Job | null> {
  return toJobById(await apiGet(jobPath(jobId), signal), jobId, expectedAccountId);
}

export async function fetchJobPlan(jobId: string, signal?: AbortSignal): Promise<JobPlan> {
  return toJobPlan(await apiGet(jobPlanPath(jobId), signal), jobId);
}

export interface CreateDryRunInput {
  /** From the resolved writable account, never inferred from the dossier. */
  readonly accountId: string;
  /** The parsed Wexia document. The backend parser is authoritative. */
  readonly typedInput: unknown;
  /** Generated once per submit attempt, so a retry is not a second job. */
  readonly idempotencyKey: string;
}

export async function createDryRun(
  input: CreateDryRunInput,
): Promise<{ jobId: string; status: JobStatus }> {
  return toCreatedJobId(
    await apiSend("/jobs/dry-runs", "POST", {
      account_id: input.accountId,
      typed_input: input.typedInput,
      idempotency_key: input.idempotencyKey,
    }),
  );
}

/**
 * Authorizes execution of a verified dry-run.
 *
 * The body carries only an idempotency key. The account comes from the parent
 * job server-side, the mode is not settable, and the backend refuses a parent
 * that is not DRY_RUN_VERIFIED.
 */
export async function createExecution(
  dryRunJobId: string,
  idempotencyKey: string,
): Promise<{ jobId: string; status: JobStatus }> {
  return toCreatedJobId(
    await apiSend(`${JOBS_PATH}/${encodeURIComponent(dryRunJobId)}/executions`, "POST", {
      idempotency_key: idempotencyKey,
    }),
  );
}
