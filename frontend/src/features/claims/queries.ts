import { useEffect, useRef } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { Claim, ClaimStatus } from "@shared/types";
import { markClaimNotificationsSeen, saveClaimAction } from "@shared/api/claims";
import { unreadCategories } from "@shared/utils/notificationFreshness";
import { ACCOUNTS_QUERY_KEY } from "@features/accounts/queries";
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

/**
 * Opening a dossier marks its new notifications seen, on the backend.
 *
 * Fires once for each distinct set of unread notifications on the claim shown:
 * a refetch that returns the same unread set does not repeat it, and a failed
 * attempt is not retried in a loop. Nothing is patched into the cache — the
 * badge disappears only when the refetched list, which the backend confirmed,
 * says so. On failure the notification simply stays new.
 *
 * Only a claim resolved from THIS account's list ever reaches here, and no
 * account id is sent: the backend takes the account from the claim.
 */
export function useMarkSeenOnOpen(accountId: string, claim: Claim | undefined) {
  const queryClient = useQueryClient();
  const markSeen = useMutation({
    mutationFn: (claimPk: string) => markClaimNotificationsSeen(claimPk),
    onSuccess: async () => {
      // BOTH caches are derived from the same category_presence rows this
      // just changed: the account's claims, and the per-account summary the
      // rail badge and the overview counters read. Refreshing only the
      // claims left "2 nouvelles notifications" in the sidebar for a dossier
      // the employee had already opened.
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: claimsQueryKey(accountId) }),
        queryClient.invalidateQueries({ queryKey: ACCOUNTS_QUERY_KEY }),
      ]);
    },
  });
  const { mutate } = markSeen;
  const attempted = useRef<string | null>(null);

  const claimPk = claim?.claimPk;
  const unread = claim === undefined ? [] : unreadCategories(claim).sort();
  const signature = claimPk === undefined || unread.length === 0 ? null : JSON.stringify([claimPk, ...unread]);

  useEffect(() => {
    if (signature === null || claimPk === undefined || attempted.current === signature) return;
    attempted.current = signature;
    mutate(claimPk);
  }, [claimPk, mutate, signature]);

  return {
    /** The attempt for the claim currently shown failed; it is still new. */
    failed: markSeen.isError && markSeen.variables === claimPk,
    /**
     * The backend confirmed it. Reported only after the request succeeded --
     * never on optimistic intent -- so the confirmation an employee reads is
     * always a fact about stored state.
     */
    confirmed: markSeen.isSuccess && markSeen.variables === claimPk,
  };
}
