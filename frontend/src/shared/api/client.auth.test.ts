import { afterEach, describe, expect, it, vi } from "vitest";
import {
  apiGet,
  apiLogin,
  apiSend,
  apiSessionProbe,
  ApiRequestError,
  setUnauthorizedListener,
} from "./client";
import { shouldRetryQuery, createQueryClient } from "../../app/providers";
import { clearCookies, mockApiError, mockJsonResponse, setCsrfCookie } from "../../test/apiMock";

afterEach(() => {
  setUnauthorizedListener(null);
});

describe("apiLogin", () => {
  it("posts JSON with credentials and needs no CSRF cookie", async () => {
    clearCookies();
    const stub = mockJsonResponse({ user_id: "u", username: "a", role: "admin", csrf_token: "t" });
    await apiLogin({ username: "a", password: "pw" });

    const [path, init] = stub.mock.calls[0] as [string, RequestInit];
    expect(path).toBe("/auth/login");
    expect(init.method).toBe("POST");
    expect(init.credentials).toBe("include");
    expect(JSON.parse(String(init.body))).toEqual({ username: "a", password: "pw" });
    expect((init.headers as Record<string, string>)["X-CSRF-Token"]).toBeUndefined();
  });

  it("maps a 401 to INVALID_CREDENTIALS without notifying the session listener", async () => {
    const listener = vi.fn();
    setUnauthorizedListener(listener);
    mockApiError(401, "INVALID_CREDENTIALS", "nope");
    await expect(apiLogin({ username: "a", password: "b" })).rejects.toMatchObject({
      apiError: { status: 401, code: "INVALID_CREDENTIALS", message: "Identifiants incorrects." },
    });
    expect(listener).not.toHaveBeenCalled();
  });

  it("is still same-origin checked by the request pipeline", async () => {
    const stub = mockJsonResponse({});
    await expect(apiGet("//evil.example/auth/login")).rejects.toBeInstanceOf(ApiRequestError);
    expect(stub).not.toHaveBeenCalled();
  });
});

describe("apiSessionProbe", () => {
  it("does not notify the listener on 401", async () => {
    const listener = vi.fn();
    setUnauthorizedListener(listener);
    mockApiError(401, "UNAUTHENTICATED", "x");
    await expect(apiSessionProbe()).rejects.toBeInstanceOf(ApiRequestError);
    expect(listener).not.toHaveBeenCalled();
  });
});

describe("unauthorized listener", () => {
  it("is notified when an authenticated GET or state change returns 401 UNAUTHENTICATED", async () => {
    setCsrfCookie("t");
    const listener = vi.fn();
    setUnauthorizedListener(listener);
    mockApiError(401, "UNAUTHENTICATED", "x");
    await expect(apiGet("/accounts")).rejects.toBeInstanceOf(ApiRequestError);
    await expect(apiSend("/claims/1", "POST", {})).rejects.toBeInstanceOf(ApiRequestError);
    expect(listener).toHaveBeenCalledTimes(2);
  });

  it("is not notified for other failures", async () => {
    const listener = vi.fn();
    setUnauthorizedListener(listener);
    mockApiError(403, "FORBIDDEN", "x");
    await expect(apiGet("/accounts")).rejects.toBeInstanceOf(ApiRequestError);
    expect(listener).not.toHaveBeenCalled();
  });

  it("stops notifying after unsubscribe", async () => {
    const listener = vi.fn();
    const off = setUnauthorizedListener(listener);
    off();
    mockApiError(401, "UNAUTHENTICATED", "x");
    await expect(apiGet("/accounts")).rejects.toBeInstanceOf(ApiRequestError);
    expect(listener).not.toHaveBeenCalled();
  });
});

describe("query retry policy", () => {
  it("never retries a 401", () => {
    const error = new ApiRequestError({ status: 401, code: "UNAUTHENTICATED", message: "m" });
    expect(shouldRetryQuery(0, error)).toBe(false);
  });

  it("retries other failures once", () => {
    const error = new ApiRequestError({ status: 500, code: "INTERNAL_ERROR", message: "m" });
    expect(shouldRetryQuery(0, error)).toBe(true);
    expect(shouldRetryQuery(1, error)).toBe(false);
  });

  it("is what the production query client uses", () => {
    expect(createQueryClient().getDefaultOptions().queries?.retry).toBe(shouldRetryQuery);
  });
});
