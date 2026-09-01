import type { PortalAccount } from "@shared/types";
import { apiGet } from "./client";
import { toPortalAccounts } from "./adapters/accounts";

/** GET /accounts — the accounts the authenticated employee may see. */
export const ACCOUNTS_PATH = "/accounts";

export async function fetchAccounts(signal?: AbortSignal): Promise<PortalAccount[]> {
  return toPortalAccounts(await apiGet(ACCOUNTS_PATH, signal));
}
