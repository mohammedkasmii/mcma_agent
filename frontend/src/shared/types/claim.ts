/**
 * Types for the claim surface.
 *
 * This is the frontend representation, not the wire shape: the API sends
 * snake_case (`claim_pk`, `matricule_norm`, `updated_at`) and the adapter in
 * shared/api/adapters/claims.ts maps it here. No production component reads a
 * wire object.
 */

/**
 * The employee tracking statuses the backend defines
 * (mcma/app/api/app.py, `CLAIM_STATUSES`). There is no TODO status and no
 * other value is ever accepted or sent.
 */
export const CLAIM_STATUSES = ["NEW", "IN_PROGRESS", "WAITING", "DONE", "NOT_APPLICABLE"] as const;

export type ClaimStatus = (typeof CLAIM_STATUSES)[number];

export interface Claim {
  /** Internal identifier. Used for keys and future actions, never shown. */
  readonly claimPk: string;
  /** The account this claim belongs to, as the backend reported it. */
  readonly accountId: string;
  /** The portal's own identifier. Internal; not employee-facing identity. */
  readonly portalClaimId: string;
  /** Nullable in the portal data — preserved as null rather than "". */
  readonly reference: string | null;
  readonly insured: string | null;
  readonly police: string | null;
  /** Normalized vehicle registration. */
  readonly matricule: string | null;
  readonly lastSeenVersion: number;
  readonly accountEntity: string;
  readonly accountScope: string;
  readonly accountLabel: string;
  /** Employee tracking status. "NEW" when no action has been recorded. */
  readonly status: ClaimStatus;
  /** Latest note, or null when no action has been recorded. */
  readonly note: string | null;
  /** When the latest action was recorded, or null when there is none. */
  readonly updatedAt: string | null;
  /** Portal alert categories this claim is currently present in. */
  readonly categories: readonly string[];
}
