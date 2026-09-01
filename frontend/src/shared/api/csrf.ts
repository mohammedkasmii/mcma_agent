/**
 * CSRF token access.
 *
 * The backend (mcma/app/auth/csrf.py) issues `mcma_csrf` as a deliberately
 * non-HttpOnly cookie and requires it echoed back in the `X-CSRF-Token`
 * header on every state-changing request (double-submit cookie). The session
 * cookie `mcma_session` is HttpOnly and is never read here — it travels
 * automatically with the request and carries the actual authority.
 */

export const CSRF_COOKIE_NAME = "mcma_csrf";
export const CSRF_HEADER_NAME = "X-CSRF-Token";

/**
 * Reads the CSRF token from document.cookie, or null when it is absent.
 *
 * Cookie values are percent-encoded on the wire; the token itself is
 * URL-safe base64, so decoding is a no-op in practice but is done anyway
 * rather than assumed.
 */
export function readCsrfToken(cookieString?: string): string | null {
  const source = cookieString ?? (typeof document === "undefined" ? "" : document.cookie);
  for (const part of source.split(";")) {
    const separator = part.indexOf("=");
    if (separator === -1) continue;
    const name = part.slice(0, separator).trim();
    if (name !== CSRF_COOKIE_NAME) continue;
    const raw = part.slice(separator + 1).trim();
    if (raw.length === 0) return null;
    try {
      return decodeURIComponent(raw);
    } catch {
      return raw;
    }
  }
  return null;
}
