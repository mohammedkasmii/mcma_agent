import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { UseQueryResult } from "@tanstack/react-query";
import type { AccountsLoadState, PortalAccount } from "@shared/types";
import type { ApiError } from "@shared/types";
import {
  cancelPortalLogin,
  fetchAccounts,
  fetchLoginStatus,
  refreshNotifications,
  startPortalLogin,
} from "@shared/api/accounts";
import { isLoginActive } from "@shared/api/adapters/accounts";
import type { LoginStatus } from "@shared/api/adapters/accounts";
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

/** Bounded progress poll: only while a request is in flight, never faster than this. */
export const LOGIN_STATUS_POLL_MS = 2000;

export const loginStatusQueryKey = (accountId: string) => ["login-status", accountId] as const;

/**
 * Connecting one account.
 *
 * No credentials cross this boundary -- the mutation carries only the account
 * in the path. Two server behaviours exist:
 *  - local Windows: the POST is synchronous and the account list is refetched;
 *  - central: the POST queues a request for the employee's workstation and
 *    returns a status view. Progress is then polled -- only while the request
 *    is active -- and "connected" is shown only after the SERVER reports
 *    SUCCEEDED and the account list has been refetched.
 */
export function useAccountLogin(accountId: string) {
  const queryClient = useQueryClient();
  const [engaged, setEngaged] = useState(false);
  const key = loginStatusQueryKey(accountId);

  const start = useMutation({
    mutationFn: () => startPortalLogin(accountId),
    onSuccess: async (result) => {
      if (result.kind === "onboarding") {
        queryClient.setQueryData(key, result.status);
        setEngaged(true);
        return;
      }
      await queryClient.invalidateQueries({ queryKey: ACCOUNTS_QUERY_KEY });
    },
  });

  const statusQuery = useQuery({
    queryKey: key,
    queryFn: ({ signal }) => fetchLoginStatus(accountId, signal),
    enabled: engaged,
    retry: false,
    staleTime: 0,
    refetchInterval: (query) =>
      query.state.status !== "error" && isLoginActive(query.state.data?.state) ? LOGIN_STATUS_POLL_MS : false,
  });

  const cancel = useMutation({
    mutationFn: () => cancelPortalLogin(accountId),
    onSuccess: (status) => {
      queryClient.setQueryData(key, status);
    },
  });

  const status: LoginStatus | undefined = engaged ? statusQuery.data : undefined;
  const active = isLoginActive(status?.state);
  const requestId = status?.requestId ?? null;
  const succeeded = status?.state === "SUCCEEDED";

  useEffect(() => {
    // The server confirmed the stored session: refetch what it now reports.
    if (succeeded) void queryClient.invalidateQueries({ queryKey: ACCOUNTS_QUERY_KEY });
  }, [succeeded, requestId, queryClient]);

  return { start, cancel, status, active, statusError: engaged && statusQuery.isError ? statusQuery.error : null };
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
