import { useQuery } from "@tanstack/react-query";
import type { UseQueryResult } from "@tanstack/react-query";
import type { AccountsLoadState, PortalAccount } from "@shared/types";
import type { ApiError } from "@shared/types";
import { fetchAccounts } from "@shared/api/accounts";
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
