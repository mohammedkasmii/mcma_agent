import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { UseQueryResult } from "@tanstack/react-query";
import type { AccountsLoadState, PortalAccount } from "@shared/types";
import type { ApiError } from "@shared/types";
import { fetchAccounts, refreshNotifications, startPortalLogin } from "@shared/api/accounts";
import { claimsQueryKey } from "@features/work-queue/queries";
import { ApiRequestError } from "@shared/api/client";
import { responseShapeError } from "@shared/api/errors";
import type { AccountRailData } from "./useAccountRail";

/**
 * Accounts are server state and TanStack Query owns them.
 *
 * There is exactly one cache entry for the account list. The rail, the
 * workspace headers and the route guards all read from it, so two surfaces
 * can never disagree about which accounts exist or which are writable.
 */

export const ACCOUNTS_QUERY_KEY = ["accounts"] as const;

export function useAccountsQuery(): UseQueryResult<PortalAccount[], Error> {
  return useQuery({
    queryKey: ACCOUNTS_QUERY_KEY,
    queryFn: ({ signal }) => fetchAccounts(signal),
  });
}

/** Turns any thrown value into an employee-facing error record. */
export function toApiError(error: unknown): ApiError {
  return error instanceof ApiRequestError ? error.apiError : responseShapeError();
}

/** Maps the query result onto the four states the rail renders. */
export function railStateFrom(query: UseQueryResult<PortalAccount[], Error>): AccountsLoadState {
  if (query.isPending) return "loading";
  if (query.isError) return "error";
  return (query.data ?? []).length === 0 ? "empty" : "ready";
}

export function useAccountRailData(): AccountRailData {
  const query = useAccountsQuery();
  return { state: railStateFrom(query), accounts: query.data ?? [] };
}

/**
 * Resolution of the account named in the URL against the authoritative
 * account list.
 *
 * `unknown` is a real outcome, not an error: the list loaded and this
 * account is not in it. Nothing downstream may treat it as "probably fine".
 */
export type AccountResolution =
  | { readonly status: "loading" }
  | { readonly status: "error"; readonly error: ApiError }
  | { readonly status: "unknown" }
  | { readonly status: "resolved"; readonly account: PortalAccount };

export function useAccountResolution(accountId: string | undefined): AccountResolution {
  const query = useAccountsQuery();

  if (query.isPending) return { status: "loading" };
  if (query.isError) return { status: "error", error: toApiError(query.error) };

  const account = (query.data ?? []).find((candidate) => candidate.accountId === accountId);
  return account === undefined ? { status: "unknown" } : { status: "resolved", account };
}

/**
 * Opening the portal login window for one account.
 *
 * No credentials cross this boundary — the mutation carries only the account
 * in the path. On success the account list is refetched: the connection state
 * shown to the employee is whatever the backend then reports, never a locally
 * assumed CONNECTED.
 */
export function useStartLogin(accountId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => startPortalLogin(accountId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ACCOUNTS_QUERY_KEY });
    },
  });
}

/**
 * A manual notification refresh for one account.
 *
 * Invalidates that account's claims only — a refresh on one agency must not
 * discard another's rows — and the account list, because the poll can itself
 * discover that a session has expired.
 */
export function useRefreshNotifications(accountId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => refreshNotifications(accountId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: claimsQueryKey(accountId) });
      await queryClient.invalidateQueries({ queryKey: ACCOUNTS_QUERY_KEY });
    },
  });
}
