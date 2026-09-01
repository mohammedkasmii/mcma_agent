/**
 * Same-origin path validation.
 *
 * Every request this application makes goes to its own origin. Checking that
 * a path merely begins with "/" is not enough: the browser URL parser treats
 * several strings that start with "/" as pointing somewhere else entirely.
 *
 *   //evil.example      protocol-relative — resolves to another host
 *   /\evil.example      backslashes are normalized to slashes for HTTP URLs
 *   "/\t/evil.example"  tabs, newlines and other control characters are
 *                       stripped during parsing, revealing a "//" prefix
 *
 * This matters most for state-changing requests, which attach the readable
 * mcma_csrf token: sending that token to a foreign origin would hand an
 * attacker the second half of the double-submit pair.
 *
 * Rather than blacklisting those patterns one by one, the path is resolved
 * with the real URL parser against the current origin and the resulting
 * origin is compared. Anything that does not land back on this origin is
 * refused, including tricks not enumerated above.
 */

/** Space, C0 controls and DEL — all significant to URL parsing. */
const CONTROL_OR_SPACE = /[\u0000-\u0020\u007f]/;

function currentOrigin(): string | null {
  if (typeof window === "undefined") return null;
  const origin = window.location.origin;
  return typeof origin === "string" && origin.length > 0 ? origin : null;
}

/**
 * Returns the normalized root-relative path when it provably resolves to the
 * current origin, or null when it does not.
 *
 * Null is the only failure signal: callers must refuse the request rather
 * than fall back to the original string.
 */
export function resolveSameOriginPath(path: string): string | null {
  if (typeof path !== "string" || path.length === 0) return null;

  // Rejected before parsing, because the parser would silently remove these
  // and change what the path means.
  if (CONTROL_OR_SPACE.test(path)) return null;
  if (path.includes("\\")) return null;

  // API paths are root-relative. This also rejects absolute http:// and
  // https:// URLs, and any other scheme.
  if (!path.startsWith("/")) return null;
  // Protocol-relative: "//host" is a different origin.
  if (path.startsWith("//")) return null;

  const origin = currentOrigin();
  if (origin === null) return null;

  let resolved: URL;
  try {
    resolved = new URL(path, origin);
  } catch {
    return null;
  }

  // The authoritative check. Everything above is defence in depth.
  if (resolved.origin !== origin) return null;

  return `${resolved.pathname}${resolved.search}`;
}
