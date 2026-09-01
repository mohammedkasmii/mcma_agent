import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { Claim, ClaimStatus } from "@shared/types";
import { saveClaimAction } from "@shared/api/claims";
import { claimsQueryKey, useClaimsQuery } from "@features/work-queue/queries";

/**
 * Claim reads and the one claim write.
 *
 * There is no GET /claims/{id}: a single claim is located in the account's
 * authoritative list, which is the same cache the work queue reads. That is
 * deliberate — one claim record, one source, so a detail screen and a list
 * row can never disagree.
 */

export type ClaimResolution =
  | { readonly status: "loading" }
  | { readonly status: "error"; readonly error: Error }
  | { readonly status: "unknown" }
  | { readonly status: "resolved"; readonly claim: Claim };

export function useClaimResolution(accountId: string, claimPk: string | undefined): ClaimResolution {
  const query = useClaimsQuery(accountId);

  if (query.isPending) return { status: "loading" };
  if (query.isError) return { status: "error", error: query.error };

  const claim = (query.data ?? []).find((candidate) => candidate.claimPk === claimPk);
  return claim === undefined ? { status: "unknown" } : { status: "resolved", claim };
}

export interface SaveTrackingInput {
  readonly claimPk: string;
  readonly status: ClaimStatus;
  readonly note: string | null;
}

/**
 * Records a tracking action, then refetches the account's authoritative
 * claims.
 *
 * Nothing is written into the cache optimistically. The employee sees the
 * saved state only once the backend has confirmed it, because a status that
 * appears saved but was refused is worse than one that takes a moment.
 */
export function useSaveTracking(accountId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: SaveTrackingInput) => saveClaimAction(input),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: claimsQueryKey(accountId) });
    },
  });
}
