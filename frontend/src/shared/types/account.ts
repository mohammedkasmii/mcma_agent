/**
 * Types for the portal-account surface.
 *
 * This is the frontend representation, NOT the wire shape. The HTTP API
 * returns snake_case fields (`account_id`, `connection_state`,
 * `session_active`); STEP 2 adds a centralized adapter in shared/api/ that
 * maps the backend wire representation into the camelCase interface below,
 * so no screen ever reads a raw response object. That adapter does not
 * exist yet.
 *
 * The field meanings come from GET /accounts and the backend remains the
 * authority on all of them: which accounts are visible, which are writable,
 * and what their connection state is. The frontend never re-derives
 * `writable` from `entity` — it reads the field.
 */

export type PortalEntity = "MCMA" | "MAMDA";

/** Agency scope (e.g. a city). Left open: the backend owns the vocabulary. */
export type PortalScope = string;

/**
 * What the backend has established about a portal session.
 *
 * UNVERIFIED is the honest middle: session material exists, but this
 * process has not seen evidence it is live. It is NOT "expired" -- the
 * remedy is to check, not to make someone type an OTP again.
 */
export type ConnectionState =
  | "CONNECTED"
  | "UNVERIFIED"
  | "RECONNECT_REQUIRED"
  | "NOT_CONNECTED";

export interface PortalAccount {
  /** Opaque server identifier. Used in routes, never shown as primary copy. */
  readonly accountId: string;
  /** Employee-facing name supplied by the backend. */
  readonly label: string;
  readonly entity: PortalEntity;
  readonly scope: PortalScope;
  readonly connectionState: ConnectionState;
  readonly sessionActive: boolean;
  /**
   * Whether this account may be the target of an automation job.
   * Decided by the backend. MAMDA accounts are never writable.
   */
  readonly writable: boolean;
}

/** Loading lifecycle for any account-scoped surface. */
export type AccountsLoadState = "loading" | "empty" | "ready" | "error";
