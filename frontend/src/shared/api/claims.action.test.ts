import { describe, expect, it } from "vitest";
import { claimActionPath, NOTE_MAX_LENGTH, saveClaimAction } from "./claims";
import { ApiRequestError } from "./client";
import { clearCookies, mockApiError, mockJsonResponse, setCsrfCookie } from "../../test/apiMock";
import { CLAIM_NEW_WIRE } from "../../test/fixtures";

const CLAIM_PK = CLAIM_NEW_WIRE.claim_pk;

describe("claimActionPath", () => {
  it("targets the claim's own action endpoint", () => {
    expect(claimActionPath(CLAIM_PK)).toBe(`/claims/${CLAIM_PK}/action`);
  });

  it("encodes an identifier that would otherwise change the path", () => {
    expect(claimActionPath("a/b")).toBe("/claims/a%2Fb/action");
  });
});

describe("saveClaimAction", () => {
  it("posts the status and note through the central client", async () => {
    setCsrfCookie();
    const stub = mockJsonResponse({ claim_pk: CLAIM_PK, status: "DONE", note: "n", version: 2 });

    await saveClaimAction({ claimPk: CLAIM_PK, status: "DONE", note: "n" });

    const [path, init] = stub.mock.calls[0] as [string, RequestInit];
    expect(path).toBe(`/claims/${CLAIM_PK}/action`);
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ status: "DONE", note: "n" });
  });

  it("sends credentials and the CSRF header from the central client", async () => {
    setCsrfCookie("token-under-test");
    const stub = mockJsonResponse({ claim_pk: CLAIM_PK, status: "NEW", note: null, version: 1 });

    await saveClaimAction({ claimPk: CLAIM_PK, status: "NEW", note: null });

    const init = stub.mock.calls[0]?.[1] as RequestInit;
    expect(init.credentials).toBe("include");
    expect((init.headers as Record<string, string>)["X-CSRF-Token"]).toBe("token-under-test");
  });

  it("sends a null note rather than an empty string", async () => {
    setCsrfCookie();
    const stub = mockJsonResponse({ claim_pk: CLAIM_PK, status: "WAITING", note: null, version: 3 });

    await saveClaimAction({ claimPk: CLAIM_PK, status: "WAITING", note: null });

    expect(JSON.parse(stub.mock.calls[0]?.[1] ? ((stub.mock.calls[0][1] as RequestInit).body as string) : "{}")).toEqual({
      status: "WAITING",
      note: null,
    });
  });

  it("never sends an account id as an authorization input", async () => {
    setCsrfCookie();
    const stub = mockJsonResponse({ claim_pk: CLAIM_PK, status: "DONE", note: null, version: 4 });

    await saveClaimAction({ claimPk: CLAIM_PK, status: "DONE", note: null });

    const body = JSON.parse((stub.mock.calls[0]?.[1] as RequestInit).body as string) as Record<
      string,
      unknown
    >;
    // The backend resolves access from the claim itself.
    expect(body).not.toHaveProperty("account_id");
    expect(body).not.toHaveProperty("actor_user_id");
    expect(body).not.toHaveProperty("version");
  });

  it("accepts a note at the backend maximum length", async () => {
    setCsrfCookie();
    const note = "n".repeat(NOTE_MAX_LENGTH);
    const stub = mockJsonResponse({ claim_pk: CLAIM_PK, status: "DONE", note, version: 5 });

    await saveClaimAction({ claimPk: CLAIM_PK, status: "DONE", note });

    const body = JSON.parse((stub.mock.calls[0]?.[1] as RequestInit).body as string) as {
      note: string;
    };
    expect(body.note).toHaveLength(2000);
  });

  it("refuses to send when no CSRF cookie is readable", async () => {
    clearCookies();
    const stub = mockJsonResponse({});
    await expect(
      saveClaimAction({ claimPk: CLAIM_PK, status: "DONE", note: null }),
    ).rejects.toThrow(ApiRequestError);
    expect(stub).not.toHaveBeenCalled();
  });

  it("normalizes a backend refusal without exposing its message", async () => {
    setCsrfCookie();
    mockApiError(400, "BAD_REQUEST", "note is too long (2000 characters maximum)");

    try {
      await saveClaimAction({ claimPk: CLAIM_PK, status: "DONE", note: "x" });
      expect.unreachable("request should have failed");
    } catch (error) {
      expect((error as Error).message).not.toContain("2000 characters maximum");
    }
  });
});
