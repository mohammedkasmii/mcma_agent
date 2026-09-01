/**
 * Types for automation jobs.
 *
 * The status list is the backend's own CHECK constraint
 * (mcma/persistence/migrations/0002_…sql) — all nineteen values, not a subset
 * the frontend finds convenient. An unrecognised status fails the read rather
 * than being displayed as something else.
 */

export const JOB_STATUSES = [
  // dry run
  "QUEUED",
  "PLANNING",
  "NEEDS_REVIEW",
  "PLANNED",
  "READ_ONLY_IDENTITY_CHECK",
  "DRY_RUN_VERIFIED",
  "IDENTITY_FAILED",
  // execution
  "ACQUIRING_ACCOUNT_LOCK",
  "IDENTITY_VERIFYING",
  "IDENTITY_VERIFIED",
  "WRITING",
  "VERIFYING",
  "WRITE_ABORTED",
  "READY_FOR_HUMAN_REVIEW",
  "AWAITING_HUMAN_CONFIRMATION",
  "HUMAN_CONFIRMED_COMPLETE",
  "INTERRUPTED_NEEDS_HUMAN_REVIEW",
  "ABORTED_ON_RESTART",
  "ERROR",
] as const;

export type JobStatus = (typeof JOB_STATUSES)[number];

export const JOB_MODES = ["DRY_RUN", "EXECUTE"] as const;

export type JobMode = (typeof JOB_MODES)[number];

export interface Job {
  readonly jobId: string;
  readonly accountId: string;
  /** The dry-run an execution came from, or null for a dry-run itself. */
  readonly parentJobId: string | null;
  /** Server-determined. Never chosen by this frontend. */
  readonly workflowName: string;
  readonly mode: JobMode;
  readonly status: JobStatus;
  readonly reasonCode: string | null;
  /** A digest of the plan, not its content. */
  readonly planHash: string | null;
  readonly createdAt: string;
  readonly startedAt: string | null;
  readonly finishedAt: string | null;
}

export interface PlanStep {
  readonly rubriqueId: string;
  /** Decimal strings, kept exactly as sent. Never parsed into a number. */
  readonly ht: string;
  readonly tva: string;
  readonly vetuste: string;
}

export interface PlanFieldIntent {
  readonly selector: string;
  readonly value: string;
}

export interface PlanReviewItem {
  readonly reason: string;
  readonly detail: string | null;
}

export interface JobPlan {
  readonly jobId: string;
  readonly planHash: string;
  readonly repairWorkflow: string;
  readonly steps: readonly PlanStep[];
  readonly fieldIntents: readonly PlanFieldIntent[];
  readonly needsReview: readonly PlanReviewItem[];
}
