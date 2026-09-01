import type { Claim, ClaimStatus } from "@shared/types";
import { apiGet, apiSend } from "./client";
import { toClaims } from "./adapters/claims";

/** GET /claims — the claims of one portal account. */
export const CLAIMS_PATH = "/claims";

/**
 * Reads one account's work queue.
 *
 * Always scoped: the unscoped form of this endpoint returns every account the
 * employee can see, which is not what a per-account work queue means. The
 * account id goes through URLSearchParams, so an identifier containing a
 * separator or a reserved character cannot alter the query string.
 */
export function claimsPath(accountId: string): string {
  const query = new URLSearchParams({ account_id: accountId });
  return `${CLAIMS_PATH}?${query.toString()}`;
}

export async function fetchClaims(accountId: string, signal?: AbortSignal): Promise<Claim[]> {
  return toClaims(await apiGet(claimsPath(accountId), signal), accountId);
}

/** The backend's own limit on a tracking note (mcma/app/api/app.py). */
export const NOTE_MAX_LENGTH = 2000;

export interface ClaimActionInput {
  readonly claimPk: string;
  readonly status: ClaimStatus;
  /** Optional. Null clears the note rather than sending an empty string. */
  readonly note: string | null;
}

export function claimActionPath(claimPk: string): string {
  return `${CLAIMS_PATH}/${encodeURIComponent(claimPk)}/action`;
}

/**
 * Records an employee tracking action.
 *
 * The body carries only `status` and `note`. No account id is sent: the
 * backend resolves access from the claim's own account, and supplying one
 * here would be inventing an authorization input it does not accept.
 *
 * CSRF and credentials come from the central client; nothing is added here.
 *
 * The response is not adapted into a claim. The authoritative claim list is
 * refetched instead, so the interface never shows a locally assembled record
 * as if the server had confirmed it.
 */
export async function saveClaimAction(input: ClaimActionInput): Promise<void> {
  await apiSend(claimActionPath(input.claimPk), "POST", {
    status: input.status,
    note: input.note,
  });
}
