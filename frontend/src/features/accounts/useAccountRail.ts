import type { AccountsLoadState, PortalAccount } from "@shared/types";

export interface AccountRailData {
  readonly state: AccountsLoadState;
  readonly accounts: readonly PortalAccount[];
}

/**
 * The rail's data source.
 *
 * STEP 1 connects to no backend, so this reports the loading state and an
 * empty list. It deliberately returns no invented accounts: a placeholder
 * record here would be indistinguishable from a real portal account in the
 * interface. The TanStack Query call against GET /accounts replaces the body
 * of this hook without any change to AccountRail.
 */
export function useAccountRail(): AccountRailData {
  return { state: "loading", accounts: [] };
}
