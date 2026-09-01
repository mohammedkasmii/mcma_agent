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
