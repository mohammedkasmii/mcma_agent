import type { PortalAccount } from "@shared/types";

/**
 * Synthetic accounts, used by tests only.
 *
 * Identifiers and scopes here are deliberately fictional: no production
 * account id or agency name appears in the source tree, and the shipped
 * application renders no account record it did not receive from the
 * backend.
 */

export const WRITABLE_ACCOUNT: PortalAccount = {
  accountId: "test-account-writable",
  label: "Compte de test A",
  entity: "MCMA",
  scope: "ZONE-A",
  connectionState: "CONNECTED",
  sessionActive: true,
  writable: true,
};

export const READ_ONLY_ACCOUNT: PortalAccount = {
  accountId: "test-account-readonly",
  label: "Compte de test B",
  entity: "MAMDA",
  scope: "ZONE-B",
  connectionState: "RECONNECT_REQUIRED",
  sessionActive: false,
  writable: false,
};

export const TEST_ACCOUNTS: readonly PortalAccount[] = [WRITABLE_ACCOUNT, READ_ONLY_ACCOUNT];
