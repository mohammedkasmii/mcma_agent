import { describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { renderAppAt } from "../../test/renderApp";
import { mockApiError, mockNetworkFailure } from "../../test/apiMock";
import {
  CLAIM_NEW_WIRE,
  CLAIM_TRACKED_WIRE,
  READ_ONLY_ACCOUNT_WIRE,
  READ_ONLY_CLAIM_WIRE,
  TEST_ACCOUNTS_WIRE,
  WRITABLE_ACCOUNT_CLAIMS_WIRE,
  WRITABLE_ACCOUNT_WIRE,
} from "../../test/fixtures";
import { claimStatusLabel } from "@shared/utils/claimStatus";

const WORK = (id: string) => `/accounts/${id}/work`;

/**
 * Answers /accounts and /claims from one stub, so the account route resolves
 * normally and the claims request is the thing under test. The stub records
 * every URL it was called with.
 */
function mockBackend(claimsByAccount: Record<string, readonly unknown[]>) {
  const stub = vi.fn((url: string) => {
    const body = url.startsWith("/accounts")
      ? { accounts: TEST_ACCOUNTS_WIRE }
      : { claims: claimsByAccount[new URL(url, "http://localhost").searchParams.get("account_id") ?? ""] ?? [] };
    return Promise.resolve({
      ok: true,
      status: 200,
      text: () => Promise.resolve(JSON.stringify(body)),
    } as unknown as Response);
  });
  vi.stubGlobal("fetch", stub);
  return stub;
}

const WRITABLE_ID = WRITABLE_ACCOUNT_WIRE.account_id;
const READ_ONLY_ID = READ_ONLY_ACCOUNT_WIRE.account_id;

describe("work queue states", () => {
  it("shows a loading state before the claims arrive", () => {
    mockBackend({ [WRITABLE_ID]: WRITABLE_ACCOUNT_CLAIMS_WIRE });
    renderAppAt(WORK(WRITABLE_ID));
    expect(screen.getByText("Chargement des comptes portail")).toBeInTheDocument();
  });

  it("renders the claims the backend returned", async () => {
    mockBackend({ [WRITABLE_ID]: WRITABLE_ACCOUNT_CLAIMS_WIRE });
    renderAppAt(WORK(WRITABLE_ID));

    expect(await screen.findByText("REF-0001")).toBeInTheDocument();
    expect(screen.getByText("Assuré Test Un")).toBeInTheDocument();
    expect(screen.getByText("0000-A-0")).toBeInTheDocument();
    expect(screen.getByText("POL-0001")).toBeInTheDocument();
    expect(screen.getByText("Catégorie test 1")).toBeInTheDocument();
    expect(screen.getByText("Note de suivi test")).toBeInTheDocument();
  });

  it("says plainly when the account has no claims", async () => {
    mockBackend({ [WRITABLE_ID]: [] });
    renderAppAt(WORK(WRITABLE_ID));
    expect(await screen.findByText("Aucun sinistre dans cette file")).toBeInTheDocument();
  });

  it("reports an unreachable server rather than an empty queue", async () => {
    mockNetworkFailure();
    renderAppAt(WORK(WRITABLE_ID));
    // The account list fails first; the queue never claims to be empty.
    expect(await screen.findByText("Impossible de charger vos comptes")).toBeInTheDocument();
    expect(screen.queryByText("Aucun sinistre dans cette file")).toBeNull();
  });

  it("reports a claims failure without the raw backend message", async () => {
    const stub = vi.fn((url: string) => {
      if (url.startsWith("/accounts")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          text: () => Promise.resolve(JSON.stringify({ accounts: TEST_ACCOUNTS_WIRE })),
        } as unknown as Response);
      }
      return Promise.resolve({
        ok: false,
        status: 403,
        text: () =>
          Promise.resolve(
            JSON.stringify({
              error: "FORBIDDEN",
              message: "account access denied for principal",
              correlation_id: "0".repeat(32),
            }),
          ),
      } as unknown as Response);
    });
    vi.stubGlobal("fetch", stub);

    renderAppAt(WORK(WRITABLE_ID));

    expect(await screen.findByText("Impossible de charger la file de travail")).toBeInTheDocument();
    expect(screen.getByText("Vous n'avez pas accès à cet élément.")).toBeInTheDocument();
    expect(screen.queryByText(/account access denied/)).toBeNull();
    expect(screen.queryByText("Aucun sinistre dans cette file")).toBeNull();
  });

  it("does not show a claims list when the account list itself failed", async () => {
    mockApiError(401, "UNAUTHENTICATED", "authentication required");
    renderAppAt(WORK(WRITABLE_ID));
    expect(await screen.findByText("Impossible de charger vos comptes")).toBeInTheDocument();
    expect(screen.queryByRole("table")).toBeNull();
  });
});

describe("account scoping", () => {
  it("requests claims for the account named in the URL", async () => {
    const stub = mockBackend({ [WRITABLE_ID]: WRITABLE_ACCOUNT_CLAIMS_WIRE });
    renderAppAt(WORK(WRITABLE_ID));
    await screen.findByText("REF-0001");

    const claimsCalls = stub.mock.calls.map(([url]) => url as string).filter((url) => url.startsWith("/claims"));
    expect(claimsCalls).toContain(`/claims?account_id=${WRITABLE_ID}`);
    // Never the unscoped form, which would return every visible account.
    expect(claimsCalls).not.toContain("/claims");
  });

  it("uses the new account id when the route changes account", async () => {
    const stub = mockBackend({
      [WRITABLE_ID]: WRITABLE_ACCOUNT_CLAIMS_WIRE,
      [READ_ONLY_ID]: [READ_ONLY_CLAIM_WIRE],
    });
    renderAppAt(WORK(READ_ONLY_ID));
    await screen.findByText("REF-0003");

    const claimsCalls = stub.mock.calls.map(([url]) => url as string).filter((url) => url.startsWith("/claims"));
    expect(claimsCalls).toContain(`/claims?account_id=${READ_ONLY_ID}`);
    expect(claimsCalls).not.toContain(`/claims?account_id=${WRITABLE_ID}`);
    // The other account's rows are not on screen.
    expect(screen.queryByText("REF-0001")).toBeNull();
  });

  it("keeps the work queue available for a read-only account", async () => {
    mockBackend({ [READ_ONLY_ID]: [READ_ONLY_CLAIM_WIRE] });
    renderAppAt(WORK(READ_ONLY_ID));

    expect(await screen.findByText("REF-0003")).toBeInTheDocument();
    // The label appears on the row badge and in the status filter, so both
    // occurrences are expected here.
    expect(screen.getAllByText(claimStatusLabel("WAITING")).length).toBeGreaterThan(0);
    // The capability label still describes automation, not visibility.
    expect(screen.getAllByText("Lecture seule").length).toBeGreaterThan(0);
  });

  it("refuses rows the backend attributed to another account", async () => {
    // A response scoped to one account that carries another account's row.
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) =>
        Promise.resolve({
          ok: true,
          status: 200,
          text: () =>
            Promise.resolve(
              JSON.stringify(
                url.startsWith("/accounts")
                  ? { accounts: TEST_ACCOUNTS_WIRE }
                  : { claims: [READ_ONLY_CLAIM_WIRE] },
              ),
            ),
        } as unknown as Response),
      ),
    );

    renderAppAt(WORK(WRITABLE_ID));

    expect(await screen.findByText("Impossible de charger la file de travail")).toBeInTheDocument();
    expect(screen.queryByText("REF-0003")).toBeNull();
  });
});

describe("what the queue shows", () => {
  it("never uses an internal identifier as visible identity", async () => {
    mockBackend({ [WRITABLE_ID]: WRITABLE_ACCOUNT_CLAIMS_WIRE });
    renderAppAt(WORK(WRITABLE_ID));
    await screen.findByText("REF-0001");

    expect(screen.queryByText(CLAIM_NEW_WIRE.claim_pk)).toBeNull();
    expect(screen.queryByText(CLAIM_NEW_WIRE.portal_claim_id)).toBeNull();
    expect(screen.queryByText(CLAIM_TRACKED_WIRE.claim_pk)).toBeNull();
  });

  it("offers no tracking control, because recording one is not built yet", async () => {
    mockBackend({ [WRITABLE_ID]: WRITABLE_ACCOUNT_CLAIMS_WIRE });
    renderAppAt(WORK(WRITABLE_ID));
    await screen.findByText("REF-0001");

    expect(screen.queryByRole("button", { name: /Enregistrer/ })).toBeNull();
    expect(screen.queryByRole("textbox", { name: /note/i })).toBeNull();
  });

  it("makes no state-changing request", async () => {
    const stub = mockBackend({ [WRITABLE_ID]: WRITABLE_ACCOUNT_CLAIMS_WIRE });
    renderAppAt(WORK(WRITABLE_ID));
    await screen.findByText("REF-0001");

    await waitFor(() => expect(stub).toHaveBeenCalled());
    for (const [, init] of stub.mock.calls as unknown as [string, RequestInit][]) {
      expect(init.method).toBe("GET");
    }
  });

  it("renders an absent portal field as absence", async () => {
    mockBackend({ [WRITABLE_ID]: [CLAIM_TRACKED_WIRE] });
    renderAppAt(WORK(WRITABLE_ID));
    await screen.findByText("REF-0002");
    // police and categories are absent on this fixture.
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });
});
