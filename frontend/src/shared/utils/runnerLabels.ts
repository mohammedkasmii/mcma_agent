import type { OwnRunnerStatus, RunnerStatus, SessionState } from "@shared/types";
import type { StatusTone } from "@shared/ui";

export const RUNNER_STATUS_LABELS: Record<RunnerStatus, string> = {
  ONLINE: "En ligne",
  OFFLINE: "Hors ligne",
  REVOKED: "Révoqué",
};

export const RUNNER_STATUS_TONES: Record<RunnerStatus, StatusTone> = {
  ONLINE: "connected",
  OFFLINE: "reconnect",
  REVOKED: "failed",
};

export const SESSION_STATE_LABELS: Record<SessionState, string> = {
  NOT_CONFIGURED: "Non configuré",
  LOGIN_REQUIRED: "Connexion requise",
  READY: "Prêt",
  ERROR: "Erreur",
};

/** The two portal accounts a workstation runner serves. */
const RUNNER_CITIES: Record<string, string> = {
  "acct-mcma-oujda": "Oujda",
  "acct-mcma-nador": "Nador",
};

/** "MCMA Oujda" for a known runner account id, otherwise null. */
export function runnerAccountName(accountId: string): string | null {
  const city = RUNNER_CITIES[accountId];
  return city === undefined ? null : `MCMA ${city}`;
}

export const OWN_RUNNER_STATUS_SENTENCES: Record<OwnRunnerStatus, string> = {
  UNPAIRED: "Poste agent non associé",
  OFFLINE: "Poste agent hors ligne",
  REVOKED: "Poste agent révoqué",
  ONLINE: "Poste agent connecté",
};

/** Session sentence for the account being viewed; null when it is not a runner account. */
export function sessionSentence(accountId: string, state: SessionState | undefined): string | null {
  const name = runnerAccountName(accountId);
  if (name === null) return null;
  if (state === "READY") return "Prêt";
  if (state === "ERROR") return `Erreur de session ${name}`;
  return `Connexion ${name} requise`;
}
