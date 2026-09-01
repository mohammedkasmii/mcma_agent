import type {
  Job,
  JobMode,
  JobPlan,
  JobStatus,
  PlanFieldIntent,
  PlanReviewItem,
  PlanStep,
} from "@shared/types";
import { JOB_MODES, JOB_STATUSES } from "@shared/types";
import { ApiRequestError } from "../client";
import { responseShapeError } from "../errors";

/**
 * The single wire-to-frontend mapping for jobs and plans.
 *
 * Pure and fail-closed, like the other adapters. A status outside the
 * backend's own set fails the read: an automation whose state the interface
 * cannot name is one it must not describe, and guessing would be worse than
 * showing an error.
 *
 * Money is never touched. `ht`, `tva` and `vetuste` arrive as decimal strings
 * and are carried through as strings, because parsing them into floats and
 * reserializing is exactly how a reviewed plan stops matching what the agent
 * will type.
 */

function fail(): never {
  throw new ApiRequestError(responseShapeError());
}

function requireRecord(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) fail();
  return value as Record<string, unknown>;
}

function requireString(value: unknown): string {
  if (typeof value !== "string" || value.length === 0) fail();
  return value;
}

function requireNullableString(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  if (typeof value !== "string") fail();
  return value;
}

function requireArray(value: unknown): unknown[] {
  if (!Array.isArray(value)) fail();
  return value;
}

function requireStatus(value: unknown): JobStatus {
  const status = requireString(value);
  if (!(JOB_STATUSES as readonly string[]).includes(status)) fail();
  return status as JobStatus;
}

function requireMode(value: unknown): JobMode {
  const mode = requireString(value);
  if (!(JOB_MODES as readonly string[]).includes(mode)) fail();
  return mode as JobMode;
}

/**
 * Maps one job row.
 *
 * `parent_job_id`, `reason_code`, `plan_hash`, `started_at` and `finished_at`
 * are genuinely null for most of a job's life and stay null — an absent
 * finish time is not the same fact as a finish time of now.
 */
export function toJob(row: unknown): Job {
  const wire = requireRecord(row);
  return {
    jobId: requireString(wire["job_id"]),
    accountId: requireString(wire["account_id"]),
    parentJobId: requireNullableString(wire["parent_job_id"]),
    workflowName: requireString(wire["workflow_name"]),
    mode: requireMode(wire["mode"]),
    status: requireStatus(wire["status"]),
    reasonCode: requireNullableString(wire["reason_code"]),
    planHash: requireNullableString(wire["plan_hash"]),
    createdAt: requireString(wire["created_at"]),
    startedAt: requireNullableString(wire["started_at"]),
    finishedAt: requireNullableString(wire["finished_at"]),
  };
}

/**
 * Maps the GET /jobs envelope and picks out one job.
 *
 * `expectedAccountId` is the account whose workspace is open. A job belonging
 * elsewhere fails closed rather than being drawn under this account's header:
 * the backend already authorizes access, and this refuses to mislabel what it
 * returned.
 *
 * A job the backend did not return is `null`, not an error — the caller
 * decides whether a missing job is a fail-closed condition (it is).
 */
export function toJobById(body: unknown, jobId: string, expectedAccountId: string): Job | null {
  const envelope = requireRecord(body);
  const jobs = requireArray(envelope["jobs"]).map(toJob);
  const job = jobs.find((candidate) => candidate.jobId === jobId);
  if (job === undefined) return null;
  if (job.accountId !== expectedAccountId) fail();
  return job;
}

/**
 * Maps the whole GET /jobs collection.
 *
 * No account is expected here: this is the cross-account list the backend
 * already filtered to what the employee may see. Per-job screens keep their
 * own account cross-check; this does not weaken it.
 */
export function toJobs(body: unknown): Job[] {
  const envelope = requireRecord(body);
  return requireArray(envelope["jobs"]).map(toJob);
}

/** Maps the reduced body of the two job-creating endpoints. */
export function toCreatedJobId(body: unknown): { jobId: string; status: JobStatus } {
  const wire = requireRecord(body);
  return { jobId: requireString(wire["job_id"]), status: requireStatus(wire["status"]) };
}

function toPlanStep(row: unknown): PlanStep {
  const wire = requireRecord(row);
  return {
    rubriqueId: requireString(wire["rubrique_id"]),
    ht: requireString(wire["ht"]),
    tva: requireString(wire["tva"]),
    vetuste: requireString(wire["vetuste"]),
  };
}

function toFieldIntent(row: unknown): PlanFieldIntent {
  const wire = requireRecord(row);
  return { selector: requireString(wire["selector"]), value: requireString(wire["value"]) };
}

function toReviewItem(row: unknown): PlanReviewItem {
  const wire = requireRecord(row);
  return { reason: requireString(wire["reason"]), detail: requireNullableString(wire["detail"]) };
}

/**
 * Maps GET /jobs/{job_id}/plan.
 *
 * There is no expected_identity field to read: the backend deliberately omits
 * the registration and claim id from this projection, and nothing here
 * reconstructs them.
 *
 * `expectedJobId` is the job the plan was asked for. A body naming a
 * different job fails closed rather than being displayed: this plan is what
 * an employee reads before authorizing writes, and a plan belonging to
 * another run is the one thing it must never be.
 */
export function toJobPlan(body: unknown, expectedJobId: string): JobPlan {
  const wire = requireRecord(body);
  const jobId = requireString(wire["job_id"]);
  if (jobId !== expectedJobId) fail();
  return {
    jobId,
    planHash: requireString(wire["plan_hash"]),
    repairWorkflow: requireString(wire["repair_workflow"]),
    steps: requireArray(wire["steps"]).map(toPlanStep),
    fieldIntents: requireArray(wire["form_field_intents"]).map(toFieldIntent),
    needsReview: requireArray(wire["needs_review"]).map(toReviewItem),
  };
}
