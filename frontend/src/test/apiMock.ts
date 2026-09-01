import { vi } from "vitest";
import type { Mock } from "vitest";

/**
 * Network doubles for tests.
 *
 * Tests stub `fetch` rather than a module, so what is under test is the real
 * client: its credentials mode, its headers, its parsing and its error
 * normalization all execute exactly as they do in the browser.
 */

function installFetch(implementation: (...args: unknown[]) => unknown): Mock {
  const stub = vi.fn(implementation);
  vi.stubGlobal("fetch", stub);
  return stub;
}

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    text: () => Promise.resolve(JSON.stringify(body)),
  } as unknown as Response;
}

/** A successful response with an arbitrary JSON body, for every call. */
export function mockJsonResponse(body: unknown, status = 200): Mock {
  return installFetch(() => Promise.resolve(jsonResponse(status, body)));
}

/** A successful GET /accounts carrying the given wire rows. */
export function mockAccounts(rows: readonly unknown[]): Mock {
  return mockJsonResponse({ accounts: rows });
}

/** A backend error response in the real { error, message, correlation_id } shape. */
export function mockApiError(status: number, code: string, serverMessage: string): Mock {
  return installFetch(() =>
    Promise.resolve(
      jsonResponse(status, {
        error: code,
        message: serverMessage,
        correlation_id: "00000000000000000000000000000000",
      }),
    ),
  );
}

/** The server could not be reached at all. */
export function mockNetworkFailure(): Mock {
  return installFetch(() => Promise.reject(new TypeError("Failed to fetch")));
}

/** A response body that is not JSON at all. */
export function mockNonJsonResponse(text: string): Mock {
  return installFetch(() =>
    Promise.resolve({
      ok: true,
      status: 200,
      text: () => Promise.resolve(text),
    } as unknown as Response),
  );
}

/**
 * A routing stub answering several endpoints from one fetch double, so a
 * screen test exercises the real client and real adapters end to end.
 *
 * Handlers are matched in order against the request path; the first match
 * wins. An unmatched path answers 404 in the backend's own error shape rather
 * than throwing, so a missing handler surfaces as a visible failure state.
 */
export interface RouteHandler {
  readonly match: (url: string, init: RequestInit) => boolean;
  readonly status?: number;
  readonly body: unknown | ((url: string, init: RequestInit) => unknown);
}

export function mockRoutes(handlers: readonly RouteHandler[]): Mock {
  const stub = vi.fn((url: string, init: RequestInit = {}) => {
    const handler = handlers.find((candidate) => candidate.match(url, init));
    if (handler === undefined) {
      return Promise.resolve(
        jsonResponse(404, { error: "NOT_FOUND", message: "no handler", correlation_id: "0" }),
      );
    }
    const body = typeof handler.body === "function" ? handler.body(url, init) : handler.body;
    return Promise.resolve(jsonResponse(handler.status ?? 200, body));
  });
  vi.stubGlobal("fetch", stub as unknown as typeof fetch);
  return stub;
}

/** Makes the CSRF cookie readable, as the backend issues it. */
export function setCsrfCookie(value = "test-csrf-token"): void {
  Object.defineProperty(document, "cookie", { configurable: true, get: () => `mcma_csrf=${value}` });
}

export function clearCookies(): void {
  Object.defineProperty(document, "cookie", { configurable: true, get: () => "" });
}
