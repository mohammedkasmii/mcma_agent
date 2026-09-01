import { useQuery } from "@tanstack/react-query";
import type { UseQueryResult } from "@tanstack/react-query";
import type { Claim } from "@shared/types";
import { fetchClaims } from "@shared/api/claims";

/**
 * Claims are server state and TanStack Query owns them. There is no second
 * claims store.
 *
 * The key carries the account, so each account has its own cache entry.
 * Navigating to another account does not read the previous account's rows:
 * the new key has no data yet, and the queue shows its loading state rather
 * than someone else's claims under a new heading.
 */
export const CLAIMS_QUERY_KEY = "claims";

export function claimsQueryKey(accountId: string) {
  return [CLAIMS_QUERY_KEY, accountId] as const;
}

export function useClaimsQuery(accountId: string): UseQueryResult<Claim[], Error> {
  return useQuery({
    queryKey: claimsQueryKey(accountId),
    queryFn: ({ signal }) => fetchClaims(accountId, signal),
  });
}
