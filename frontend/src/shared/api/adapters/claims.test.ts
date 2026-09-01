import { describe, expect, it } from "vitest";
import { toClaim, toClaims } from "./claims";
import { ApiRequestError } from "../client";
import { claimsPath, fetchClaims } from "../claims";
import { mockJsonResponse } from "../../../test/apiMock";
import {
  CLAIM_NEW_WIRE,
  CLAIM_TRACKED_WIRE,
  READ_ONLY_CLAIM_WIRE,
  WRITABLE_ACCOUNT_CLAIMS_WIRE,
  WRITABLE_ACCOUNT_WIRE,
} from "../../../test/fixtures";

const ACCOUNT_ID = WRITABLE_ACCOUNT_WIRE.account_id;

describe("toClaim", () => {
  it("maps every snake_case wire field onto the frontend record", () => {
    expect(toClaim(CLAIM_NEW_WIRE)).toEqual({
      claimPk: "test-claim-1",
      accountId: ACCOUNT_ID,
      portalClaimId: "portal-1",
      reference: "REF-0001",
      insured: "Assuré Test Un",
      police: "POL-0001",
      matricule: "0000-A-0",
      lastSeenVersion: 4,
      accountEntity: "MCMA",
      accountScope: "ZONE-A",
      accountLabel: "Compte de test A",
      status: "NEW",
      note: null,
      updatedAt: null,
      categories: ["Catégorie test 1", "Catégorie test 2"],
    });
  });

  it("leaves no snake_case key on the mapped record", () => {
    const mapped = toClaim(CLAIM_NEW_WIRE) as unknown as Record<string, unknown>;
    for (const key of Object.keys(mapped)) {
      expect(key).not.toContain("_");
    }
  });

  it("preserves a null note and updated_at rather than flattening them", () => {
    const untracked = toClaim(CLAIM_NEW_WIRE);
    expect(untracked.note).toBeNull();
    expect(untracked.updatedAt).toBeNull();

    const tracked = toClaim(CLAIM_TRACKED_WIRE);
    expect(tracked.note).toBe("Note de suivi test");
    expect(tracked.updatedAt).toBe("2026-01-15T09:30:00Z");
  });

  it("preserves a null portal field", () => {
    expect(toClaim(CLAIM_TRACKED_WIRE).police).toBeNull();
    expect(toClaim({ ...CLAIM_NEW_WIRE, reference: null }).reference).toBeNull();
  });

  it("maps categories, including the empty case", () => {
    expect(toClaim(CLAIM_NEW_WIRE).categories).toEqual([
      "Catégorie test 1",
      "Catégorie test 2",
    ]);
    expect(toClaim(CLAIM_TRACKED_WIRE).categories).toEqual([]);
  });

  it("maps all five backend statuses", () => {
    for (const status of ["NEW", "IN_PROGRESS", "WAITING", "DONE", "NOT_APPLICABLE"]) {
      expect(toClaim({ ...CLAIM_NEW_WIRE, status }).status).toBe(status);
    }
  });

  it("fails closed on an unknown status", () => {
    expect(() => toClaim({ ...CLAIM_NEW_WIRE, status: "TODO" })).toThrow(ApiRequestError);
    expect(() => toClaim({ ...CLAIM_NEW_WIRE, status: "" })).toThrow(ApiRequestError);
    expect(() => toClaim({ ...CLAIM_NEW_WIRE, status: null })).toThrow(ApiRequestError);
  });

  it("fails closed on a missing or mistyped field", () => {
    const { claim_pk: _dropped, ...incomplete } = CLAIM_NEW_WIRE;
    expect(() => toClaim(incomplete)).toThrow(ApiRequestError);
    expect(() => toClaim({ ...CLAIM_NEW_WIRE, last_seen_version: "4" })).toThrow(ApiRequestError);
    expect(() => toClaim({ ...CLAIM_NEW_WIRE, insured: 7 })).toThrow(ApiRequestError);
    expect(() => toClaim({ ...CLAIM_NEW_WIRE, categories: "none" })).toThrow(ApiRequestError);
    expect(() => toClaim({ ...CLAIM_NEW_WIRE, categories: [1] })).toThrow(ApiRequestError);
  });

  it("carries only an employee-facing message when it fails", () => {
    try {
      toClaim({ ...CLAIM_NEW_WIRE, status: "TODO" });
      expect.unreachable("adapter should have failed");
    } catch (error) {
      expect((error as ApiRequestError).apiError.code).toBe("INVALID_RESPONSE");
      expect((error as ApiRequestError).message).not.toContain("TODO");
      expect((error as ApiRequestError).message).not.toContain("REF-0001");
    }
  });
});

describe("toClaims", () => {
  it("maps the claims envelope", () => {
    const claims = toClaims({ claims: WRITABLE_ACCOUNT_CLAIMS_WIRE }, ACCOUNT_ID);
    expect(claims).toHaveLength(2);
    expect(claims[0]?.reference).toBe("REF-0001");
  });

  it("accepts an empty claim list", () => {
    expect(toClaims({ claims: [] }, ACCOUNT_ID)).toEqual([]);
  });

  it("fails closed when the envelope is not the expected shape", () => {
    expect(() => toClaims({}, ACCOUNT_ID)).toThrow(ApiRequestError);
    expect(() => toClaims({ claims: {} }, ACCOUNT_ID)).toThrow(ApiRequestError);
    expect(() => toClaims(null, ACCOUNT_ID)).toThrow(ApiRequestError);
    expect(() => toClaims([CLAIM_NEW_WIRE], ACCOUNT_ID)).toThrow(ApiRequestError);
  });

  it("refuses a row belonging to another account", () => {
    // The request was scoped to one account; a row from elsewhere would be
    // drawn under that account's heading and read as its work.
    expect(() => toClaims({ claims: [READ_ONLY_CLAIM_WIRE] }, ACCOUNT_ID)).toThrow(
      ApiRequestError,
    );
    expect(() =>
      toClaims({ claims: [CLAIM_NEW_WIRE, READ_ONLY_CLAIM_WIRE] }, ACCOUNT_ID),
    ).toThrow(ApiRequestError);
  });
});

describe("claimsPath", () => {
  it("scopes the request to one account", () => {
    expect(claimsPath("test-account-writable")).toBe("/claims?account_id=test-account-writable");
  });

  it("encodes an identifier that would otherwise alter the query", () => {
    expect(claimsPath("a&b=c d/e")).toBe("/claims?account_id=a%26b%3Dc+d%2Fe");
    expect(claimsPath("x#y")).toBe("/claims?account_id=x%23y");
  });
});

describe("fetchClaims", () => {
  it("requests the resolved account through the central client", async () => {
    const fetchStub = mockJsonResponse({ claims: WRITABLE_ACCOUNT_CLAIMS_WIRE });
    await fetchClaims(ACCOUNT_ID);

    const [path, init] = fetchStub.mock.calls[0] as [string, RequestInit];
    expect(path).toBe(`/claims?account_id=${ACCOUNT_ID}`);
    expect(init.credentials).toBe("include");
    expect(init.method).toBe("GET");
    expect((init.headers as Record<string, string>)["X-CSRF-Token"]).toBeUndefined();
  });

  it("returns adapted frontend records", async () => {
    mockJsonResponse({ claims: WRITABLE_ACCOUNT_CLAIMS_WIRE });
    const claims = await fetchClaims(ACCOUNT_ID);
    expect(claims.map((claim) => claim.status)).toEqual(["NEW", "IN_PROGRESS"]);
  });

  it("refuses a response carrying another account's rows", async () => {
    mockJsonResponse({ claims: [READ_ONLY_CLAIM_WIRE] });
    await expect(fetchClaims(ACCOUNT_ID)).rejects.toThrow(ApiRequestError);
  });
});
