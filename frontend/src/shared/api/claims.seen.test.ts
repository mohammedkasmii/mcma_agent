import { describe, expect, it } from "vitest";
import { claimNotificationsSeenPath, markClaimNotificationsSeen } from "./claims";
import { ApiRequestError } from "./client";
import { mockApiError, mockJsonResponse, setCsrfCookie } from "../../test/apiMock";
import { CLAIM_NEW_WIRE } from "../../test/fixtures";

const CLAIM_PK = CLAIM_NEW_WIRE.claim_pk;

describe("claimNotificationsSeenPath", () => {
  it("targets the claim's own notifications", () => {
    expect(claimNotificationsSeenPath(CLAIM_PK)).toBe(`/claims/${CLAIM_PK}/notifications/seen`);
  });

  it("encodes an identifier that would otherwise change the path", () => {
    expect(claimNotificationsSeenPath("a/b")).toBe("/claims/a%2Fb/notifications/seen");
  });
});

describe("markClaimNotificationsSeen", () => {
  it("posts with credentials and CSRF, and no body at all", async () => {
    setCsrfCookie("token-under-test");
    const stub = mockJsonResponse({ claim_pk: CLAIM_PK, marked_seen: 1 });

    await markClaimNotificationsSeen(CLAIM_PK);

    const [path, init] = stub.mock.calls[0] as [string, RequestInit];
    expect(path).toBe(`/claims/${CLAIM_PK}/notifications/seen`);
    expect(init.method).toBe("POST");
    expect(init.credentials).toBe("include");
    expect((init.headers as Record<string, string>)["X-CSRF-Token"]).toBe("token-under-test");
    // No account id, no status: the backend takes the account from the claim.
    expect(init.body).toBeUndefined();
  });

  it("rejects when the backend refuses", async () => {
    setCsrfCookie();
    mockApiError(403, "FORBIDDEN", "insufficient permission");
    await expect(markClaimNotificationsSeen(CLAIM_PK)).rejects.toThrow(ApiRequestError);
  });
});
