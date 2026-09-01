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
