import type { ConnectionState, PortalAccount } from "@shared/types";

/**
 * Pure formatting for portal-account identity and state.
 *
 * Centralised so that every screen names an account the same way. Nothing
 * here decides anything: writability and connection state arrive from the
 * backend and are only turned into words.
 */

/** "MCMA • OUJDA" — the form an employee reads to know where they are. */
export function formatAccountIdentity(account: Pick<PortalAccount, "entity" | "scope">): string {
  return `${account.entity} • ${account.scope.toUpperCase()}`;
}

const CONNECTION_LABELS: Record<ConnectionState, string> = {
  CONNECTED: "Connecté",
  RECONNECT_REQUIRED: "Reconnexion requise",
  NOT_CONNECTED: "Non connecté",
};

export function connectionLabel(state: ConnectionState): string {
  return CONNECTION_LABELS[state];
}

/**
 * Marker shape for a connection state. Colour is never the only signal, so
 * each state also gets its own outline treatment in CSS.
 */
const CONNECTION_MARKERS: Record<ConnectionState, "solid" | "half" | "hollow"> = {
  CONNECTED: "solid",
  RECONNECT_REQUIRED: "half",
  NOT_CONNECTED: "hollow",
};

export function connectionMarker(state: ConnectionState): "solid" | "half" | "hollow" {
  return CONNECTION_MARKERS[state];
}

/**
 * Employee-facing capability sentence for an account.
 * Reads the backend's `writable` field; it does not re-derive it from entity.
 */
export function capabilityLabel(account: Pick<PortalAccount, "writable">): string {
  return account.writable ? "Automatisation autorisée" : "Lecture seule";
}
