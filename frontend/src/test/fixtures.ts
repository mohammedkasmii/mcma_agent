import type { PortalAccount } from "@shared/types";
import type { AccountWire, ClaimWire } from "@shared/api/wire";

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

/**
 * Synthetic claims. Every value here is invented: the references, names,
 * registrations and police numbers are placeholders, not portal data, and no
 * personal information appears anywhere in this file.
 */

export const CLAIM_NEW_WIRE: ClaimWire = {
  claim_pk: "test-claim-1",
  account_id: WRITABLE_ACCOUNT_WIRE.account_id,
  portal_claim_id: "portal-1",
  reference: "REF-0001",
  insured: "Assuré Test Un",
  police: "POL-0001",
  matricule_norm: "0000-A-0",
  last_seen_version: 4,
  account_entity: "MCMA",
  account_scope: "ZONE-A",
  account_label: "Compte de test A",
  status: "NEW",
  note: null,
  updated_at: null,
  categories: ["Catégorie test 1", "Catégorie test 2"],
};

export const CLAIM_TRACKED_WIRE: ClaimWire = {
  claim_pk: "test-claim-2",
  account_id: WRITABLE_ACCOUNT_WIRE.account_id,
  portal_claim_id: "portal-2",
  reference: "REF-0002",
  insured: "Assuré Test Deux",
  police: null,
  matricule_norm: "1111-B-1",
  last_seen_version: 7,
  account_entity: "MCMA",
  account_scope: "ZONE-A",
  account_label: "Compte de test A",
  status: "IN_PROGRESS",
  note: "Note de suivi test",
  updated_at: "2026-01-15T09:30:00Z",
  categories: [],
};

export const READ_ONLY_CLAIM_WIRE: ClaimWire = {
  claim_pk: "test-claim-3",
  account_id: READ_ONLY_ACCOUNT_WIRE.account_id,
  portal_claim_id: "portal-3",
  reference: "REF-0003",
  insured: "Assuré Test Trois",
  police: "POL-0003",
  matricule_norm: "2222-C-2",
  last_seen_version: 2,
  account_entity: "MAMDA",
  account_scope: "ZONE-B",
  account_label: "Compte de test B",
  status: "WAITING",
  note: null,
  updated_at: null,
  categories: ["Catégorie test 3"],
};

export const WRITABLE_ACCOUNT_CLAIMS_WIRE: readonly ClaimWire[] = [
  CLAIM_NEW_WIRE,
  CLAIM_TRACKED_WIRE,
];
