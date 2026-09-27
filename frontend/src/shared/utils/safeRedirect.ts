import { resolveSameOriginPath } from "@shared/api/paths";
import { ROUTES } from "./routes";

/**
 * Validates a post-login destination.
 *
 * Only a same-app root-relative path is accepted: no "//host", no
 * backslashes, no control characters, and never the login screen itself.
 * Anything else falls back to the overview.
 */
export function safeRedirectPath(candidate: unknown): string {
  if (typeof candidate !== "string") return ROUTES.overview;
  const resolved = resolveSameOriginPath(candidate);
  if (resolved === null) return ROUTES.overview;
  const pathname = resolved.split(/[?#]/, 1)[0] ?? "";
  if (pathname === ROUTES.login || pathname.startsWith(`${ROUTES.login}/`)) return ROUTES.overview;
  // resolveSameOriginPath drops the hash; keep it out on purpose.
  return resolved;
}
