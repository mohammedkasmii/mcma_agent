import type { JobStatus } from "@shared/types";
import type { StatusTone } from "@shared/ui";

/**
 * One place where a backend job status becomes something an employee reads,
 * and one place where the interface decides what a status permits.
 *
 * The classification below mirrors mcma/execution/jobs.py: TERMINAL_STATUSES
 * there is the set nothing auto-advances out of. Anything else is genuinely
 * in flight and is the only thing worth polling.
 */

const LABELS: Record<JobStatus, string> = {
  QUEUED: "En file",
  PLANNING: "Préparation du plan",
  NEEDS_REVIEW: "Plan à vérifier",
  PLANNED: "Plan préparé",
  READ_ONLY_IDENTITY_CHECK: "Vérification d'identité",
  DRY_RUN_VERIFIED: "Plan vérifié",
  IDENTITY_FAILED: "Identité non confirmée",
  ACQUIRING_ACCOUNT_LOCK: "Préparation de l'exécution",
  IDENTITY_VERIFYING: "Vérification d'identité",
  IDENTITY_VERIFIED: "Identité confirmée",
  WRITING: "Remplissage en cours",
  VERIFYING: "Relecture des saisies",
  WRITE_ABORTED: "Remplissage interrompu",
  READY_FOR_HUMAN_REVIEW: "Vérification humaine requise",
  AWAITING_HUMAN_CONFIRMATION: "En attente de confirmation",
  HUMAN_CONFIRMED_COMPLETE: "Vérification confirmée",
  INTERRUPTED_NEEDS_HUMAN_REVIEW: "Interrompu — vérification requise",
  ABORTED_ON_RESTART: "Interrompu au redémarrage",
  ERROR: "Échec",
};

export function jobStatusLabel(status: JobStatus): string {
  return LABELS[status];
}

const TONES: Record<JobStatus, StatusTone> = {
  QUEUED: "idle",
  PLANNING: "running",
  NEEDS_REVIEW: "review",
  PLANNED: "running",
  READ_ONLY_IDENTITY_CHECK: "running",
  DRY_RUN_VERIFIED: "completed",
  IDENTITY_FAILED: "failed",
  ACQUIRING_ACCOUNT_LOCK: "running",
  IDENTITY_VERIFYING: "running",
  IDENTITY_VERIFIED: "running",
  WRITING: "running",
  VERIFYING: "running",
  WRITE_ABORTED: "failed",
  READY_FOR_HUMAN_REVIEW: "review",
  AWAITING_HUMAN_CONFIRMATION: "review",
  HUMAN_CONFIRMED_COMPLETE: "completed",
  INTERRUPTED_NEEDS_HUMAN_REVIEW: "review",
  ABORTED_ON_RESTART: "failed",
  ERROR: "failed",
};

export function jobStatusTone(status: JobStatus): StatusTone {
  return TONES[status];
}

/**
 * Statuses nothing auto-advances out of — the backend's own TERMINAL_STATUSES.
 * READY_FOR_HUMAN_REVIEW is included even though it is not terminal on the
 * backend: only an explicit employee action moves it, so polling it changes
 * nothing.
 */
const SETTLED: readonly JobStatus[] = [
  "DRY_RUN_VERIFIED",
  "NEEDS_REVIEW",
  "IDENTITY_FAILED",
  "WRITE_ABORTED",
  "READY_FOR_HUMAN_REVIEW",
  "AWAITING_HUMAN_CONFIRMATION",
  "HUMAN_CONFIRMED_COMPLETE",
  "INTERRUPTED_NEEDS_HUMAN_REVIEW",
  "ABORTED_ON_RESTART",
  "ERROR",
];

/** True while the backend is still moving the job on its own. */
export function isJobInFlight(status: JobStatus): boolean {
  return !SETTLED.includes(status);
}

/**
 * The single gate on execution authorization.
 *
 * Only a verified dry-run qualifies. NEEDS_REVIEW and IDENTITY_FAILED are not
 * warnings to click past — they are why this returns false, and there is no
 * argument or override that changes the answer.
 */
export function canAuthorizeExecution(status: JobStatus): boolean {
  return status === "DRY_RUN_VERIFIED";
}

/** A dry-run that ended without producing an authorizable plan. */
export function isDryRunBlocked(status: JobStatus): boolean {
  return status === "NEEDS_REVIEW" || status === "IDENTITY_FAILED";
}

/**
 * Statuses where an execution still needs an operator's attention.
 *
 * Not the same question as "is the backend still moving it". The backend
 * treats AWAITING_HUMAN_CONFIRMATION as settled — nothing advances it on its
 * own — but the account lease is still held and the run is not finished until
 * a person confirms or reports a problem. Dropping it from this set would
 * make an occupied account look free.
 *
 * Genuine outcomes are excluded: HUMAN_CONFIRMED_COMPLETE, and every failure
 * or interruption, are things to read about on the run, not things awaiting
 * an operator on the shell.
 */
const OPERATOR_ACTIVE: readonly JobStatus[] = [
  "QUEUED",
  "PLANNING",
  "PLANNED",
  "ACQUIRING_ACCOUNT_LOCK",
  "IDENTITY_VERIFYING",
  "IDENTITY_VERIFIED",
  "WRITING",
  "VERIFYING",
  "READY_FOR_HUMAN_REVIEW",
  "AWAITING_HUMAN_CONFIRMATION",
];

export function isOperatorActive(status: JobStatus): boolean {
  return OPERATOR_ACTIVE.includes(status);
}

/** The two states where the employee, not the agent, is holding the dossier. */
export function isHumanHandoff(status: JobStatus): boolean {
  return status === "READY_FOR_HUMAN_REVIEW" || status === "AWAITING_HUMAN_CONFIRMATION";
}

/**
 * Whether the backend will accept a completion attestation for this status.
 * Only AWAITING_HUMAN_CONFIRMATION does: at READY_FOR_HUMAN_REVIEW the
 * browser has not been closed yet and the backend refuses.
 */
export function canConfirmReview(status: JobStatus): boolean {
  return status === "AWAITING_HUMAN_CONFIRMATION";
}

/** A problem may be reported from either handoff status. */
export function canReportProblem(status: JobStatus): boolean {
  return isHumanHandoff(status);
}
