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
  UNVERIFIED: "Connexion à vérifier",
  RECONNECT_REQUIRED: "Reconnexion requise",
  NOT_CONNECTED: "Non connecté",
};

export function connectionLabel(state: ConnectionState): string {
  return CONNECTION_LABELS[state];
}

/** Four distinguishable shapes, so colour is never the only signal. */
export type ConnectionMarker = "solid" | "half" | "dashed" | "hollow";

/**
 * Marker shape for a connection state. Colour is never the only signal, so
 * each state also gets its own outline treatment in CSS.
 */
const CONNECTION_MARKERS: Record<ConnectionState, ConnectionMarker> = {
  CONNECTED: "solid",
  UNVERIFIED: "dashed",
  RECONNECT_REQUIRED: "half",
  NOT_CONNECTED: "hollow",
};

export function connectionMarker(state: ConnectionState): ConnectionMarker {
  return CONNECTION_MARKERS[state];
}

/**
 * Employee-facing capability sentence for an account.
 * Reads the backend's `writable` field; it does not re-derive it from entity.
 */
export function capabilityLabel(account: Pick<PortalAccount, "writable">): string {
  return account.writable ? "Automatisation autorisée" : "Lecture seule";
}
