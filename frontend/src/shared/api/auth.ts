import type { AuthSession } from "@shared/types";
import { apiLogin, apiSend, apiSessionProbe } from "./client";
import { toAuthSession } from "./adapters/auth";

/** GET /auth/me as the initial probe: a 401 is "signed out", not "expired". */
export async function fetchSession(signal?: AbortSignal): Promise<AuthSession> {
  return toAuthSession(await apiSessionProbe(signal));
}

/**
 * POST /auth/login. The response (which includes a csrf_token) is discarded:
 * the token is delivered in the readable cookie, and the full session is
 * re-read from /auth/me. Nothing from it is stored.
 */
export async function login(username: string, password: string): Promise<void> {
  await apiLogin({ username, password });
}

/** POST /auth/logout (CSRF header attached by the client). */
export async function logout(): Promise<void> {
  await apiSend("/auth/logout", "POST", {});
}
