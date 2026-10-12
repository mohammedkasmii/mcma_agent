import type { LoginStatus } from "@shared/api/adapters/accounts";

export interface LoginProgressMessage {
  readonly text: string;
  readonly tone: "progress" | "success" | "error";
}

/** French sentences for each failure outcome the server may record. */
const FAILURE_TEXT: Readonly<Record<string, string>> = {
  LOGIN_WINDOW_CLOSED: "La fenêtre de connexion a été fermée avant la fin. Cliquez à nouveau pour réessayer.",
  LOGIN_TIMED_OUT: "Délai de connexion dépassé : la connexion n'a pas été terminée à temps. Réessayez.",
  LOGIN_PAGE_UNREACHABLE: "La page de connexion SinAuto est inaccessible depuis votre poste. Réessayez plus tard.",
  UPLOAD_FAILED: "La session n'a pas pu être enregistrée sur le serveur. Réessayez.",
  RUNNER_BUSY: "Votre poste de travail est occupé par une autre opération. Réessayez dans un instant.",
  RUNNER_OFFLINE: "Votre poste de travail est hors ligne. Lancez l'application MCMA sur votre poste puis réessayez.",
  RUNNER_SHUTDOWN: "L'application MCMA de votre poste s'est arrêtée. Relancez-la puis réessayez.",
  ACCESS_REVOKED: "Votre accès à ce compte ou à votre poste a changé. Contactez un administrateur.",
};

const INTERNAL_FAILURE = "Une erreur interne est survenue pendant la connexion. Réessayez.";
const EXPIRED = "La demande a expiré avant la fin de la connexion. Réessayez.";

/** Maps a server-confirmed status view to what the employee reads. Null for IDLE. */
export function loginProgressMessage(status: LoginStatus): LoginProgressMessage | null {
  switch (status.state) {
    case "IDLE":
      return null;
    case "QUEUED":
      return { tone: "progress", text: "Demande envoyée : en attente du poste de travail…" };
    case "OPENING_WINDOW":
      return { tone: "progress", text: "Ouverture de la fenêtre de connexion sur votre poste…" };
    case "WINDOW_OPENED":
      return { tone: "progress", text: "La fenêtre de connexion SinAuto est ouverte sur votre poste de travail." };
    case "WAITING_FOR_LOGIN":
      return {
        tone: "progress",
        text: "En attente de votre connexion : saisissez vos identifiants et le code OTP dans la fenêtre SinAuto.",
      };
    case "SUCCEEDED":
      return { tone: "success", text: "Le serveur a confirmé : le compte est connecté." };
    case "CANCELLED":
      return status.outcomeCode === "RUNNER_SHUTDOWN"
        ? { tone: "error", text: FAILURE_TEXT["RUNNER_SHUTDOWN"] as string }
        : { tone: "error", text: "Connexion annulée." };
    case "EXPIRED":
      return { tone: "error", text: EXPIRED };
    case "FAILED":
      return {
        tone: "error",
        text: (status.outcomeCode !== null ? FAILURE_TEXT[status.outcomeCode] : undefined) ?? INTERNAL_FAILURE,
      };
  }
}
