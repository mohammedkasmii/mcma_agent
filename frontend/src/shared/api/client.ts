import type { ApiError } from "@shared/types";
import { networkError, normalizeApiError, offOriginError, responseShapeError } from "./errors";
import { CSRF_HEADER_NAME, readCsrfToken } from "./csrf";
import { resolveSameOriginPath } from "./paths";

/**
 * The one place HTTP happens.
 *
 * Requests are same-origin and carry credentials, so the HttpOnly
 * `mcma_session` cookie travels with them without this code ever reading it.
 * "Same-origin" is proved, not assumed: every path goes through
 * resolveSameOriginPath before anything else happens, so a path that would
 * resolve off-origin never reaches fetch and never causes the CSRF token to
 * be read.
 *
 * Everything that can go wrong — transport failure, a non-2xx response, an
 * unparseable body — leaves this module as an ApiRequestError carrying a
 * normalized, employee-facing ApiError. No server message, exception text,
 * portal HTML or unexpected response body is ever passed through.
 */

/** The state-changing methods this application supports. */
export type StateChangingMethod = "POST" | "PUT" | "PATCH" | "DELETE";

/** Methods that do not change state and therefore need no CSRF token. */
const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

export class ApiRequestError extends Error {
  readonly apiError: ApiError;

  constructor(apiError: ApiError) {
    // The Error message is the employee-facing sentence, so even an
    // accidental render of this error cannot leak server text.
    super(apiError.message);
    this.name = "ApiRequestError";
    this.apiError = apiError;
  }
}

interface RequestOptions {
  readonly method?: "GET" | StateChangingMethod;
  /** Serialized as JSON. Only used by state-changing methods. */
  readonly body?: unknown;
  readonly signal?: AbortSignal;
}

/**
 * Safely reads a response body as JSON.
 * Returns undefined rather than throwing: the caller decides what an
 * unreadable body means for its own status code.
 */
async function readJson(response: Response): Promise<unknown> {
  try {
    const text = await response.text();
    if (text.length === 0) return undefined;
    return JSON.parse(text) as unknown;
  } catch {
    return undefined;
  }
}

/**
 * Module-private on purpose: callers reach the network through apiGet or
 * apiSend, which is what keeps reads and state changes from sharing one
 * entry point where a method could be passed by mistake.
 */
async function apiRequest(path: string, options: RequestOptions = {}): Promise<unknown> {
  // First, before the CSRF cookie is read and before any request is built.
  const safePath = resolveSameOriginPath(path);
  if (safePath === null) {
    throw new ApiRequestError(offOriginError());
  }

  const method = options.method ?? "GET";
  const headers: Record<string, string> = { Accept: "application/json" };

  if (!SAFE_METHODS.has(method)) {
    // Double-submit cookie: the backend rejects a state-changing request
    // whose header token does not match the cookie. Failing here rather
    // than sending a request that is certain to be refused gives the
    // employee the truthful reason.
    const token = readCsrfToken();
    if (token === null) {
      throw new ApiRequestError(normalizeApiError(0, { error: "CSRF_UNAVAILABLE" }));
    }
    headers[CSRF_HEADER_NAME] = token;
  }

  if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
  }

  let response: Response;
  try {
    response = await fetch(safePath, {
      method,
      credentials: "include",
      headers,
      ...(options.body === undefined ? {} : { body: JSON.stringify(options.body) }),
      ...(options.signal === undefined ? {} : { signal: options.signal }),
    });
  } catch {
    throw new ApiRequestError(networkError());
  }

  if (!response.ok) {
    throw new ApiRequestError(normalizeApiError(response.status, await readJson(response)));
  }

  const body = await readJson(response);
  if (body === undefined) {
    throw new ApiRequestError(responseShapeError());
  }
  return body;
}

/** Reads a resource. Never sends a CSRF token; never changes state. */
export function apiGet(path: string, signal?: AbortSignal): Promise<unknown> {
  return apiRequest(path, signal === undefined ? {} : { signal });
}

/**
 * Sends a state-changing request with the CSRF header attached.
 *
 * No application code calls this yet: STEP 2 performs no state-changing
 * request. It exists so that when one is built there is no second place
 * where headers, credentials and error shaping get decided.
 */
export function apiSend(
  path: string,
  method: StateChangingMethod,
  body?: unknown,
): Promise<unknown> {
  return apiRequest(path, body === undefined ? { method } : { method, body });
}
