import type { AccountsLoadState, PortalAccount } from "@shared/types";
import { useAccountRailData } from "./queries";

export interface AccountRailData {
  readonly state: AccountsLoadState;
  readonly accounts: readonly PortalAccount[];
}

/**
 * The rail's data source.
 *
 * Backed by the single TanStack Query cache entry for GET /accounts, so the
 * rail, the workspace headers and the route guards all read the same
 * authoritative list. There is no second account store.
 */
export function useAccountRail(): AccountRailData {
  return useAccountRailData();
}
