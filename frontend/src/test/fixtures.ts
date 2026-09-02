import type { PortalAccount } from "@shared/types";
import type { AccountWire, ClaimWire, JobWire } from "@shared/api/wire";

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

/** A second writable account, for tests that switch between two of them. */
export const SECOND_WRITABLE_ACCOUNT_WIRE: AccountWire = {
  account_id: "test-account-writable-2",
  label: "Compte de test C",
  entity: "MCMA",
  scope: "ZONE-C",
  session_active: true,
  connection_state: "CONNECTED",
  writable: true,
};

export const TEST_ACCOUNTS_WIRE: readonly AccountWire[] = [
  WRITABLE_ACCOUNT_WIRE,
  READ_ONLY_ACCOUNT_WIRE,
  SECOND_WRITABLE_ACCOUNT_WIRE,
];

export const SECOND_WRITABLE_ACCOUNT: PortalAccount = {
  accountId: "test-account-writable-2",
  label: "Compte de test C",
  entity: "MCMA",
  scope: "ZONE-C",
  connectionState: "CONNECTED",
  sessionActive: true,
  writable: true,
};

export const TEST_ACCOUNTS: readonly PortalAccount[] = [
  WRITABLE_ACCOUNT,
  READ_ONLY_ACCOUNT,
  SECOND_WRITABLE_ACCOUNT,
];

/** Stored session material with no live confirmation. */
export const UNVERIFIED_ACCOUNT_WIRE: AccountWire = {
  account_id: "test-account-unverified",
  label: "Compte de test D",
  entity: "MCMA",
  scope: "ZONE-D",
  session_active: true,
  connection_state: "UNVERIFIED",
  writable: true,
};

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

/** Synthetic automation jobs and plan. No dossier content appears here. */

export const DRY_RUN_JOB_WIRE: JobWire = {
  job_id: "test-job-dry-1",
  account_id: WRITABLE_ACCOUNT_WIRE.account_id,
  parent_job_id: null,
  workflow_name: "test_workflow",
  mode: "DRY_RUN",
  status: "DRY_RUN_VERIFIED",
  reason_code: null,
  plan_hash: "0000000000000000000000000000000000000000000000000000000000000000",
  created_at: "2026-01-15T09:00:00Z",
  started_at: "2026-01-15T09:00:05Z",
  finished_at: "2026-01-15T09:01:00Z",
};

export const EXECUTION_JOB_WIRE: JobWire = {
  ...DRY_RUN_JOB_WIRE,
  job_id: "test-job-exec-1",
  parent_job_id: DRY_RUN_JOB_WIRE.job_id,
  mode: "EXECUTE",
  status: "ACQUIRING_ACCOUNT_LOCK",
  finished_at: null,
};

export const PLAN_WIRE = {
  job_id: DRY_RUN_JOB_WIRE.job_id,
  plan_hash: DRY_RUN_JOB_WIRE.plan_hash,
  repair_workflow: "MODE_NORMAL",
  steps: [
    { rubrique_id: "RUB-TEST-1", ht: "1200.50", tva: "240.10", vetuste: "0.00" },
    { rubrique_id: "RUB-TEST-2", ht: "340.00", tva: "68.00", vetuste: "15.25" },
  ],
  form_field_intents: [
    { selector: "#champ-test-1", value: "valeur-test-1" },
    { selector: "#champ-test-2", value: "valeur-test-2" },
  ],
  needs_review: [],
};

export const PLAN_NEEDS_REVIEW_WIRE = {
  ...PLAN_WIRE,
  needs_review: [
    { reason: "RUBRIQUE_AMBIGUE", detail: "deux correspondances possibles" },
    { reason: "MONTANT_ABSENT", detail: null },
  ],
};

/** A minimal synthetic dossier document. Not a real Wexia payload. */
export const SYNTHETIC_DOSSIER = { dossier: { test: true }, lignes: [] };
