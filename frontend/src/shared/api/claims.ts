import type { Claim } from "@shared/types";
import { apiGet } from "./client";
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
