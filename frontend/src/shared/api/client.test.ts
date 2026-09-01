import { describe, expect, it } from "vitest";
import { apiGet, ApiRequestError, apiSend } from "./client";
import { fetchAccounts, ACCOUNTS_PATH } from "./accounts";
import { CSRF_COOKIE_NAME } from "./csrf";
import {
  mockAccounts,
  mockApiError,
  mockJsonResponse,
  mockNetworkFailure,
  mockNonJsonResponse,
} from "../../test/apiMock";
import { TEST_ACCOUNTS, TEST_ACCOUNTS_WIRE } from "../../test/fixtures";

function setCsrfCookie(value: string): void {
  Object.defineProperty(document, "cookie", {
    configurable: true,
    get: () => `${CSRF_COOKIE_NAME}=${value}`,
  });
}

function clearCookies(): void {
  Object.defineProperty(document, "cookie", { configurable: true, get: () => "" });
}

describe("apiGet", () => {
  it("sends credentials so the session cookie travels with the request", async () => {
    const fetchStub = mockAccounts([]);
    await apiGet(ACCOUNTS_PATH);

    const [path, init] = fetchStub.mock.calls[0] as [string, RequestInit];
    expect(path).toBe("/accounts");
    expect(init.credentials).toBe("include");
  });

  it("requests the same origin with a root-relative path", async () => {
    const fetchStub = mockAccounts([]);
    await apiGet(ACCOUNTS_PATH);
    expect(fetchStub.mock.calls[0]?.[0]).toBe("/accounts");
  });

  it("uses GET and attaches no CSRF header", async () => {
    clearCookies();
    const fetchStub = mockAccounts([]);
    await apiGet(ACCOUNTS_PATH);

    const init = fetchStub.mock.calls[0]?.[1] as RequestInit;
    expect(init.method).toBe("GET");
    expect((init.headers as Record<string, string>)["X-CSRF-Token"]).toBeUndefined();
  });

  it("normalizes a backend error without exposing the server message", async () => {
    mockApiError(403, "MAMDA_ACCOUNT_NOT_WRITABLE", "this account is notification-only");

    await expect(apiGet(ACCOUNTS_PATH)).rejects.toThrow(ApiRequestError);
    try {
      await apiGet(ACCOUNTS_PATH);
    } catch (error) {
      const apiError = (error as ApiRequestError).apiError;
      expect(apiError.status).toBe(403);
      expect(apiError.code).toBe("MAMDA_ACCOUNT_NOT_WRITABLE");
      expect(apiError.message).toBe("Ce compte est en lecture seule.");
      expect((error as Error).message).not.toContain("notification-only");
    }
  });

  it("reports an unreachable server rather than a transport exception", async () => {
    mockNetworkFailure();
    try {
      await apiGet(ACCOUNTS_PATH);
      expect.unreachable("request should have failed");
    } catch (error) {
      expect((error as ApiRequestError).apiError.code).toBe("NETWORK");
      expect((error as Error).message).not.toContain("Failed to fetch");
    }
  });

  it("refuses a body that is not JSON instead of parsing it loosely", async () => {
    mockNonJsonResponse("<html><body>portal login</body></html>");
    try {
      await apiGet(ACCOUNTS_PATH);
      expect.unreachable("request should have failed");
    } catch (error) {
      expect((error as ApiRequestError).apiError.code).toBe("INVALID_RESPONSE");
      expect((error as Error).message).not.toContain("<html>");
    }
  });
});

describe("apiSend", () => {
  it("attaches the CSRF token from the mcma_csrf cookie", async () => {
    setCsrfCookie("token-under-test");
    const fetchStub = mockJsonResponse({ status: "ok" });

    await apiSend("/example", "POST", { field: 1 });

    const init = fetchStub.mock.calls[0]?.[1] as RequestInit;
    const headers = init.headers as Record<string, string>;
    expect(init.method).toBe("POST");
    expect(headers["X-CSRF-Token"]).toBe("token-under-test");
    expect(headers["Content-Type"]).toBe("application/json");
    expect(init.credentials).toBe("include");
    expect(init.body).toBe(JSON.stringify({ field: 1 }));
  });

  it("refuses to send a state-changing request with no CSRF cookie", async () => {
    clearCookies();
    const fetchStub = mockJsonResponse({ status: "ok" });

    await expect(apiSend("/example", "POST", {})).rejects.toThrow(ApiRequestError);
    // The request is never put on the wire: the backend would refuse it and
    // the employee would get a less truthful reason.
    expect(fetchStub).not.toHaveBeenCalled();
  });
});

describe("same-origin enforcement", () => {
  const OFF_ORIGIN = [
    "//example.invalid",
    "//example.invalid/accounts",
    "/\\example.invalid",
    "/\t/example.invalid",
    "https://example.invalid/accounts",
  ];

  it("accepts a normal API path", async () => {
    const fetchStub = mockAccounts([]);
    await apiGet(ACCOUNTS_PATH);
    expect(fetchStub).toHaveBeenCalledTimes(1);
  });

  it("refuses an off-origin path before calling fetch", async () => {
    for (const path of OFF_ORIGIN) {
      const fetchStub = mockJsonResponse({ status: "ok" });
      await expect(apiGet(path)).rejects.toThrow(ApiRequestError);
      expect(fetchStub).not.toHaveBeenCalled();
    }
  });

  it("refuses a backslash normalization trick before calling fetch", async () => {
    const fetchStub = mockJsonResponse({ status: "ok" });
    try {
      await apiGet("/\\example.invalid/accounts");
      expect.unreachable("request should have been refused");
    } catch (error) {
      expect((error as ApiRequestError).apiError.code).toBe("OFF_ORIGIN_REQUEST");
    }
    expect(fetchStub).not.toHaveBeenCalled();
  });

  it("does not send a state-changing request to an off-origin path", async () => {
    setCsrfCookie("token-under-test");
    const fetchStub = mockJsonResponse({ status: "ok" });

    await expect(apiSend("//example.invalid/jobs", "POST", {})).rejects.toThrow(ApiRequestError);
    expect(fetchStub).not.toHaveBeenCalled();
  });

  it("never exposes the CSRF token when the path is off-origin", async () => {
    // The origin check runs before the cookie is read, so the token is not
    // merely withheld from the request — it is never handled at all.
    setCsrfCookie("token-under-test");
    const fetchStub = mockJsonResponse({ status: "ok" });

    try {
      await apiSend("/\\example.invalid/jobs", "POST", { field: 1 });
      expect.unreachable("request should have been refused");
    } catch (error) {
      expect((error as ApiRequestError).apiError.code).toBe("OFF_ORIGIN_REQUEST");
      expect((error as Error).message).not.toContain("token-under-test");
      expect((error as Error).message).not.toContain("example.invalid");
    }
    expect(fetchStub).not.toHaveBeenCalled();
  });
});

describe("read and state-changing helpers stay separate", () => {
  it("does not accept a read method through apiSend", () => {
    // @ts-expect-error GET is not a state-changing method; apiGet is the read helper.
    const readMethod: Parameters<typeof apiSend>[1] = "GET";
    expect(readMethod).toBe("GET");
  });

  it("accepts every state-changing method we support", () => {
    const methods: Parameters<typeof apiSend>[1][] = ["POST", "PUT", "PATCH", "DELETE"];
    expect(methods).toHaveLength(4);
  });
});

describe("fetchAccounts", () => {
  it("returns adapted frontend records", async () => {
    mockAccounts(TEST_ACCOUNTS_WIRE);
    await expect(fetchAccounts()).resolves.toEqual(TEST_ACCOUNTS);
  });
});
