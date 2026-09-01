import type { ClaimStatus } from "@shared/types";

/**
 * The employee-facing wording for each tracking status.
 *
 * One table, used by every surface, so a status can never read one way in the
 * work queue and another way elsewhere. The keys are the backend's own values
 * and the labels are fixed.
 */
const STATUS_LABELS: Record<ClaimStatus, string> = {
  NEW: "À traiter",
  IN_PROGRESS: "En cours",
  WAITING: "En attente",
  DONE: "Traité",
  NOT_APPLICABLE: "Sans suite",
};

export function claimStatusLabel(status: ClaimStatus): string {
  return STATUS_LABELS[status];
}

/** Visual tone for a status badge. Never the only signal — the label is. */
const STATUS_TONES = {
  NEW: "running",
  IN_PROGRESS: "review",
  WAITING: "reconnect",
  DONE: "completed",
  NOT_APPLICABLE: "idle",
} as const;

export function claimStatusTone(status: ClaimStatus): (typeof STATUS_TONES)[ClaimStatus] {
  return STATUS_TONES[status];
}
