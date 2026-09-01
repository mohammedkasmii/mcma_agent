import { describe, expect, it } from "vitest";
import { networkError, normalizeApiError } from "./errors";

// Bodies here match the real wire shape from mcma/app/api/errors.py:
// { error, message, correlation_id }.

describe("normalizeApiError", () => {
  it("maps a known backend code to an employee-facing sentence", () => {
    const error = normalizeApiError(403, {
      error: "MAMDA_ACCOUNT_NOT_WRITABLE",
      message: "this account is notification-only",
      correlation_id: "0123456789abcdef",
    });
    expect(error.code).toBe("MAMDA_ACCOUNT_NOT_WRITABLE");
    expect(error.message).toBe("Ce compte est en lecture seule.");
  });

  it("never renders the server's own message", () => {
    const error = normalizeApiError(403, {
      error: "MAMDA_ACCOUNT_NOT_WRITABLE",
      message: "this account is notification-only",
      correlation_id: "0123456789abcdef",
    });
    expect(error.message).not.toContain("notification-only");
  });

  it("never renders server detail or portal markup", () => {
    const error = normalizeApiError(500, {
      error: "INTERNAL_ERROR",
      message: "Traceback (most recent call last): <html>portal</html>",
      detail: "sqlite3.OperationalError",
    });
    expect(error.message).not.toContain("Traceback");
    expect(error.message).not.toContain("<html>");
    expect(error.message).not.toContain("sqlite3");
  });

  it("falls back when the body carries no usable code", () => {
    expect(normalizeApiError(502, "<html>gateway</html>").code).toBe("UNKNOWN");
    expect(normalizeApiError(502, null).code).toBe("UNKNOWN");
    expect(normalizeApiError(502, { error: 42 }).code).toBe("UNKNOWN");
    expect(normalizeApiError(502, {}).code).toBe("UNKNOWN");
  });

  it("falls back for a code it does not recognise", () => {
    const error = normalizeApiError(400, { error: "SOME_FUTURE_CODE" });
    expect(error.code).toBe("SOME_FUTURE_CODE");
    expect(error.message).toBe("L'action n'a pas abouti. Réessayez.");
  });

  it("keeps the status for the caller", () => {
    expect(normalizeApiError(404, { error: "ACCOUNT_NOT_FOUND" }).status).toBe(404);
  });
});

describe("networkError", () => {
  it("describes an unreachable local server", () => {
    const error = networkError();
    expect(error.status).toBe(0);
    expect(error.code).toBe("NETWORK");
    expect(error.message.length).toBeGreaterThan(0);
  });
});
