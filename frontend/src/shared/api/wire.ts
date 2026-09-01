/**
 * Backend wire types.
 *
 * These describe what the HTTP API actually sends, field-for-field and in
 * its own snake_case vocabulary.
 *
 * The adapters in shared/api/adapters/ are the boundary. No production
 * component, hook or screen imports from this file, so a snake_case object
 * never reaches the UI. Test fixtures do import these interfaces, to describe
 * a wire row exactly as the backend would send it.
 *
 * Note that the adapters validate incoming values at runtime rather than
 * relying on these types: a declared type says nothing about what actually
 * arrived over the network.
 *
 * Source of truth: mcma/app/api/app.py, GET /accounts.
 */

/** One row of GET /accounts. */
export interface AccountWire {
  readonly account_id: string;
  readonly label: string;
  readonly entity: string;
  readonly scope: string;
  readonly session_active: boolean;
  readonly connection_state: string;
  readonly writable: boolean;
}

/** The GET /accounts envelope: the rows arrive under an `accounts` key. */
export interface AccountsResponseWire {
  readonly accounts: readonly AccountWire[];
}

/**
 * One row of GET /claims.
 *
 * Source of truth: mcma/app/api/app.py, `_CLAIMS_SELECT` plus the three
 * fields the endpoint attaches per row (`status`, `note`, `updated_at`) and
 * `categories`.
 *
 * Nullability follows the schema in mcma/persistence/migrations/0001_init.sql:
 * `reference`, `insured`, `police` and `matricule_norm` are nullable columns.
 * `status` is never null — the endpoint substitutes "NEW" when a claim has no
 * employee action yet — while `note` and `updated_at` are null in exactly
 * that case. `categories` is always an array, empty when the claim is in no
 * alert category.
 */
export interface ClaimWire {
  readonly claim_pk: string;
  readonly account_id: string;
  readonly portal_claim_id: string;
  readonly reference: string | null;
  readonly insured: string | null;
  readonly police: string | null;
  readonly matricule_norm: string | null;
  readonly last_seen_version: number;
  readonly account_entity: string;
  readonly account_scope: string;
  readonly account_label: string;
  readonly status: string;
  readonly note: string | null;
  readonly updated_at: string | null;
  readonly categories: readonly string[];
}

/** The GET /claims envelope: the rows arrive under a `claims` key. */
export interface ClaimsResponseWire {
  readonly claims: readonly ClaimWire[];
}
