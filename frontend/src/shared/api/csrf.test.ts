import { describe, expect, it } from "vitest";
import { CSRF_COOKIE_NAME, CSRF_HEADER_NAME, readCsrfToken } from "./csrf";

describe("readCsrfToken", () => {
  it("uses the names the backend defines", () => {
    expect(CSRF_COOKIE_NAME).toBe("mcma_csrf");
    expect(CSRF_HEADER_NAME).toBe("X-CSRF-Token");
  });

  it("reads the token when it is the only cookie", () => {
    expect(readCsrfToken("mcma_csrf=abc123")).toBe("abc123");
  });

  it("reads the token from among other cookies", () => {
    expect(readCsrfToken("other=1; mcma_csrf=abc123; another=2")).toBe("abc123");
  });

  it("does not match a cookie whose name merely ends with the token name", () => {
    expect(readCsrfToken("not_mcma_csrf=wrong")).toBeNull();
  });

  it("decodes a percent-encoded value", () => {
    expect(readCsrfToken("mcma_csrf=a%2Bb%3Dc")).toBe("a+b=c");
  });

  it("returns null when the cookie is absent or empty", () => {
    expect(readCsrfToken("")).toBeNull();
    expect(readCsrfToken("session=x")).toBeNull();
    expect(readCsrfToken("mcma_csrf=")).toBeNull();
  });

  it("never reads the HttpOnly session cookie", () => {
    // mcma_session is HttpOnly and unreadable by design; this helper has no
    // business looking for it even if something exposed it.
    expect(readCsrfToken("mcma_session=secret")).toBeNull();
  });
});
