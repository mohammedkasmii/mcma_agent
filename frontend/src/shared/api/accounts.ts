import type { PortalAccount } from "@shared/types";
import { apiGet, apiSend } from "./client";
import { toPortalAccounts, toRefreshOutcome } from "./adapters/accounts";
import type { RefreshOutcome } from "./adapters/accounts";

/** GET /accounts — the accounts the authenticated employee may see. */
export const ACCOUNTS_PATH = "/accounts";

export async function fetchAccounts(signal?: AbortSignal): Promise<PortalAccount[]> {
  return toPortalAccounts(await apiGet(ACCOUNTS_PATH, signal));
}

function accountActionPath(accountId: string, action: string): string {
  return `${ACCOUNTS_PATH}/${encodeURIComponent(accountId)}/${action}`;
}

/**
 * Asks the backend to open the real, visible SinAuto window for this account.
 *
 * The body is empty and always will be. Credentials and OTP are typed by the
 * employee into the portal's own window, which the backend's browser owns —
 * this frontend never receives, requests, stores or forwards them, and the
 * account is named in the path the backend re-authorizes, not in a body.
 *
 * The returned session id is deliberately discarded: the authoritative
 * connection state comes from refetching GET /accounts.
 */
export async function startPortalLogin(accountId: string): Promise<void> {
  await apiSend(accountActionPath(accountId, "login"), "POST", {});
}

/**
 * Runs the same notification poll the background loop runs.
 *
 * The response carries a fixed, server-chosen French sentence for a small set
 * of outcomes. That sentence is safe to show — it is chosen from an allowlist
 * on the backend, never assembled from portal text — but the outcome is not
 * used to infer connection state: GET /accounts stays the authority on that.
 */
export async function refreshNotifications(accountId: string): Promise<RefreshOutcome> {
  return toRefreshOutcome(
    await apiSend(accountActionPath(accountId, "refresh-notifications"), "POST", {}),
  );
}
