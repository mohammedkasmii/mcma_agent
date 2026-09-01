import type { PortalAccount } from "@shared/types";
import type { AccountWire } from "@shared/api/wire";

/**
 * Synthetic accounts, used by tests only.
 *
 * Identifiers, labels and scopes here are fictional: no production account
 * id, agency name or portal data appears in the source tree, and the shipped
 * application renders no account record it did not receive from the backend.
 *
 * Each account exists in two forms — the snake_case wire row the API sends
 * and the camelCase frontend record the adapter should produce — so a test
 * can assert the mapping instead of restating it.
 */

export const WRITABLE_ACCOUNT_WIRE: AccountWire = {
  account_id: "test-account-writable",
  label: "Compte de test A",
  entity: "MCMA",
  scope: "ZONE-A",
  session_active: true,
  connection_state: "CONNECTED",
  writable: true,
};

export const WRITABLE_ACCOUNT: PortalAccount = {
  accountId: "test-account-writable",
  label: "Compte de test A",
  entity: "MCMA",
  scope: "ZONE-A",
  connectionState: "CONNECTED",
  sessionActive: true,
  writable: true,
};

export const READ_ONLY_ACCOUNT_WIRE: AccountWire = {
  account_id: "test-account-readonly",
  label: "Compte de test B",
  entity: "MAMDA",
  scope: "ZONE-B",
  session_active: false,
  connection_state: "RECONNECT_REQUIRED",
  writable: false,
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

export const TEST_ACCOUNTS_WIRE: readonly AccountWire[] = [
  WRITABLE_ACCOUNT_WIRE,
  READ_ONLY_ACCOUNT_WIRE,
];

export const TEST_ACCOUNTS: readonly PortalAccount[] = [WRITABLE_ACCOUNT, READ_ONLY_ACCOUNT];

/** An id no fixture account carries, for fail-closed route tests. */
export const UNKNOWN_ACCOUNT_ID = "test-account-not-attributed";
