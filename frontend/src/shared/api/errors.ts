import type { ApiError } from "@shared/types";

/**
 * Turns anything a failed request can produce into one employee-facing
 * record. No request code exists yet (STEP 1 connects to no backend), but
 * the normalization rule is defined here first so that when the client
 * lands there is exactly one place errors are shaped.
 *
 * The wire shape is the one mcma/app/api/errors.py actually sends:
 *
 *   { "error": "<stable code>", "message": "<fixed server message>",
 *     "correlation_id": "<id>" }
 *
 * so the stable code is read from `error`, not from `code`. The normalized
 * frontend record keeps the name `code` because that is what the field means
 * to the interface.
 *
 * Rules:
 *  - the server's own `message`, any `detail`, and anything else in the body
 *    is dropped: only the stable code is trusted, and the sentence an
 *    employee reads is chosen here,
 *  - an unrecognised code or an unreadable body falls back to a generic
 *    sentence, so portal HTML, a DB detail or a stack trace can never reach
 *    the interface.
 */

const FALLBACK: ApiError = {
  status: 0,
  code: "UNKNOWN",
  message: "L'action n'a pas abouti. Réessayez.",
};

/** Keyed by codes mcma/app/api/errors.py and mcma/app/api/app.py emit. */
const MESSAGES: Record<string, string> = {
  UNAUTHENTICATED: "Votre session a expiré. Reconnectez-vous.",
  INVALID_CREDENTIALS: "Identifiants incorrects.",
  CSRF_FAILED: "Votre session a expiré. Rechargez la page.",
  FORBIDDEN: "Vous n'avez pas accès à cet élément.",
  ACCOUNT_NOT_FOUND: "Ce compte portail est introuvable.",
  MAMDA_ACCOUNT_NOT_WRITABLE: "Ce compte est en lecture seule.",
  INTERNAL_ERROR: "Le serveur a rencontré une erreur. Réessayez.",
  NETWORK: "Le serveur est injoignable. Vérifiez que MCMA est démarré.",
};

/** Only the field this module reads. The rest of the body is ignored. */
interface ErrorBodyShape {
  readonly error?: unknown;
}

function readCode(body: unknown): string | null {
  if (typeof body !== "object" || body === null) return null;
  const code = (body as ErrorBodyShape).error;
  return typeof code === "string" && code.length > 0 && code.length <= 64 ? code : null;
}

export function normalizeApiError(status: number, body: unknown): ApiError {
  const code = readCode(body);
  if (code === null) {
    return { ...FALLBACK, status };
  }
  const message = MESSAGES[code];
  return {
    status,
    code,
    message: message ?? FALLBACK.message,
  };
}

export function networkError(): ApiError {
  return { status: 0, code: "NETWORK", message: MESSAGES["NETWORK"] as string };
}
