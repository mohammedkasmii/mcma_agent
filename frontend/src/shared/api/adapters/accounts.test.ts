import { describe, expect, it } from "vitest";
import { toPortalAccount, toPortalAccounts } from "./accounts";
import { ApiRequestError } from "../client";
import {
  READ_ONLY_ACCOUNT,
  READ_ONLY_ACCOUNT_WIRE,
  TEST_ACCOUNTS,
  TEST_ACCOUNTS_WIRE,
  WRITABLE_ACCOUNT,
  WRITABLE_ACCOUNT_WIRE,
} from "../../../test/fixtures";

describe("toPortalAccount", () => {
  it("maps every snake_case wire field onto the frontend record", () => {
    expect(toPortalAccount(WRITABLE_ACCOUNT_WIRE)).toEqual(WRITABLE_ACCOUNT);
    expect(toPortalAccount(READ_ONLY_ACCOUNT_WIRE)).toEqual(READ_ONLY_ACCOUNT);
  });

  it("reads writable from the backend instead of inferring it from entity", () => {
    // A MAMDA row the backend somehow marked writable stays writable here;
    // a MCMA row marked non-writable stays non-writable. The frontend does
    // not hold an opinion — that would be a second authorization rule.
    expect(toPortalAccount({ ...READ_ONLY_ACCOUNT_WIRE, writable: true }).writable).toBe(true);
    expect(toPortalAccount({ ...WRITABLE_ACCOUNT_WIRE, writable: false }).writable).toBe(false);
  });

  it("leaves no snake_case key on the mapped record", () => {
    const mapped = toPortalAccount(WRITABLE_ACCOUNT_WIRE) as unknown as Record<string, unknown>;
    for (const key of Object.keys(mapped)) {
      expect(key).not.toContain("_");
    }
  });

  it("fails closed on a missing field", () => {
    const { writable: _dropped, ...incomplete } = WRITABLE_ACCOUNT_WIRE;
    expect(() => toPortalAccount(incomplete)).toThrow(ApiRequestError);
  });

  it("fails closed on a mistyped field", () => {
    expect(() => toPortalAccount({ ...WRITABLE_ACCOUNT_WIRE, writable: "true" })).toThrow(
      ApiRequestError,
    );
    expect(() => toPortalAccount({ ...WRITABLE_ACCOUNT_WIRE, account_id: 7 })).toThrow(
      ApiRequestError,
    );
  });

  it("fails closed on a value this frontend does not understand", () => {
    expect(() => toPortalAccount({ ...WRITABLE_ACCOUNT_WIRE, entity: "AUTRE" })).toThrow(
      ApiRequestError,
    );
    expect(() => toPortalAccount({ ...WRITABLE_ACCOUNT_WIRE, connection_state: "PENDING" })).toThrow(
      ApiRequestError,
    );
  });
});

describe("toPortalAccounts", () => {
  it("maps the accounts envelope", () => {
    expect(toPortalAccounts({ accounts: TEST_ACCOUNTS_WIRE })).toEqual(TEST_ACCOUNTS);
  });

  it("accepts an empty account list", () => {
    expect(toPortalAccounts({ accounts: [] })).toEqual([]);
  });

  it("fails closed when the envelope is not the expected shape", () => {
    expect(() => toPortalAccounts({})).toThrow(ApiRequestError);
    expect(() => toPortalAccounts({ accounts: {} })).toThrow(ApiRequestError);
    expect(() => toPortalAccounts(null)).toThrow(ApiRequestError);
    expect(() => toPortalAccounts([WRITABLE_ACCOUNT_WIRE])).toThrow(ApiRequestError);
  });

  it("carries only an employee-facing message when it fails", () => {
    try {
      toPortalAccounts({ accounts: [{ account_id: "x" }] });
      expect.unreachable("adapter should have failed");
    } catch (error) {
      expect(error).toBeInstanceOf(ApiRequestError);
      expect((error as ApiRequestError).apiError.code).toBe("INVALID_RESPONSE");
      expect((error as ApiRequestError).message).not.toContain("account_id");
    }
  });
});
