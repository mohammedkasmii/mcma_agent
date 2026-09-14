import { describe, expect, it, vi } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import listStyles from "./ClaimList.module.css";
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
import userEvent from "@testing-library/user-event";
import { accountClaimPath } from "@shared/utils/routes";

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
    expect(screen.getAllByText("Catégorie test 1").length).toBeGreaterThan(0);
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
  it("groups notifications by type with counts and filters the queue", async () => {
    const user = userEvent.setup();
    const secondCategoryClaim = {
      ...CLAIM_TRACKED_WIRE,
      categories: ["Catégorie test 2"],
    };
    mockBackend({ [WRITABLE_ID]: [CLAIM_NEW_WIRE, secondCategoryClaim] });
    renderAppAt(WORK(WRITABLE_ID));

    expect(await screen.findByRole("button", { name: /Toutes les alertes — 3 alertes/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Catégorie test 1 — 1 alerte/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Catégorie test 2 — 2 alertes/ })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Catégorie test 1 — 1 alerte/ }));
    expect(screen.getByText("REF-0001")).toBeInTheDocument();
    expect(screen.queryByText("REF-0002")).toBeNull();
    expect(screen.getByText("1 sur 2 sinistres affichés")).toBeInTheDocument();
  });

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

describe("work queue cleanup", () => {
  it("shows a readable timestamp rather than the stored ISO value", async () => {
    mockBackend({ [WRITABLE_ID]: WRITABLE_ACCOUNT_CLAIMS_WIRE });
    renderAppAt(WORK(WRITABLE_ID));

    await screen.findByText("Note de suivi test");
    expect(screen.queryByText("2026-01-15T09:30:00Z")).toBeNull();
    expect(screen.getByText(/^\d{2}\/\d{2}\/\d{4}/)).toBeInTheDocument();
  });

  it("opens the claim from its reference without exposing the internal id", async () => {
    mockBackend({ [WRITABLE_ID]: WRITABLE_ACCOUNT_CLAIMS_WIRE });
    renderAppAt(WORK(WRITABLE_ID));

    const link = await screen.findByRole("link", { name: "REF-0001" });
    expect(link).toHaveAttribute(
      "href",
      accountClaimPath(WRITABLE_ID, CLAIM_NEW_WIRE.claim_pk),
    );
    // The id is in the address only, never drawn as identity.
    expect(screen.queryByText(CLAIM_NEW_WIRE.claim_pk)).toBeNull();
  });

  it("clears local filters when the resolved account changes", async () => {
    const user = userEvent.setup();
    mockBackend({
      [WRITABLE_ID]: WRITABLE_ACCOUNT_CLAIMS_WIRE,
      [READ_ONLY_ID]: [READ_ONLY_CLAIM_WIRE],
    });
    renderAppAt(WORK(WRITABLE_ID));

    await screen.findByText("REF-0001");
    await user.type(screen.getByLabelText("Rechercher"), "REF-0001");
    await waitFor(() => expect(screen.queryByText("REF-0002")).toBeNull());

    // Switching account through the rail must not carry that search over.
    await user.click(screen.getByRole("link", { name: /MAMDA • ZONE-B/ }));

    expect(await screen.findByText("REF-0003")).toBeInTheDocument();
    expect(screen.getByLabelText("Rechercher")).toHaveValue("");
    expect(screen.getByLabelText("Suivi")).toHaveValue("ALL");
  });
});

describe("notification freshness", () => {
  const notification = (category: string, unread: boolean) => ({
    category,
    unread,
    appeared_at: unread ? "2026-02-01T08:00:00Z" : null,
    seen_at: null,
  });
  // Category 1 is new on REF-0001; category 2 is seen there.
  const NEW_IN_FIRST = {
    ...CLAIM_NEW_WIRE,
    notifications: [notification("Catégorie test 1", true), notification("Catégorie test 2", false)],
  };
  // Category 2 is new on REF-0002.
  const NEW_IN_SECOND = {
    ...CLAIM_TRACKED_WIRE,
    categories: ["Catégorie test 2"],
    notifications: [notification("Catégorie test 2", true)],
  };
  const rowOf = async (reference: string) => {
    const row = (await screen.findByRole("link", { name: reference })).closest("tr");
    expect(row).not.toBeNull();
    return row as HTMLTableRowElement;
  };

  it("badges and highlights only a dossier with an unread notification", async () => {
    mockBackend({ [WRITABLE_ID]: [NEW_IN_FIRST, CLAIM_TRACKED_WIRE] });
    renderAppAt(WORK(WRITABLE_ID));

    const fresh = await rowOf("REF-0001");
    const seen = await rowOf("REF-0002");
    const unreadRow = listStyles.unreadRow ?? "";
    expect(unreadRow).not.toBe("");
    expect(within(fresh).getByText("Nouveau")).toBeInTheDocument();
    expect(fresh).toHaveClass(unreadRow);
    expect(within(seen).queryByText("Nouveau")).toBeNull();
    expect(seen).not.toHaveClass(unreadRow);
    // Freshness is not the tracking status: Suivi still reads as recorded.
    expect(within(fresh).getByText(claimStatusLabel("NEW"))).toBeInTheDocument();
    // The reference link keeps its own name; the badge sits beside it.
    expect(within(fresh).getByRole("link", { name: "REF-0001" })).toBeInTheDocument();
  });

  it("shows every type's total and its new count, totals staying membership sums", async () => {
    mockBackend({ [WRITABLE_ID]: [NEW_IN_FIRST, NEW_IN_SECOND] });
    renderAppAt(WORK(WRITABLE_ID));

    expect(
      await screen.findByRole("button", { name: "Toutes les alertes — 3 alertes, dont 2 nouvelles" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Catégorie test 1 — 1 alerte, dont 1 nouvelle" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Catégorie test 2 — 2 alertes, dont 1 nouvelle" }),
    ).toBeInTheDocument();
    expect(screen.getByText("2 nouvelles")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Nouvelles \(2\)/ })).toBeInTheDocument();
  });

  it("shows no new count on a type with nothing new", async () => {
    mockBackend({ [WRITABLE_ID]: WRITABLE_ACCOUNT_CLAIMS_WIRE });
    renderAppAt(WORK(WRITABLE_ID));

    expect(
      await screen.findByRole("button", { name: "Catégorie test 1 — 1 alerte" }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/\d+ nouvelles?$/)).toBeNull();
    expect(screen.queryByText("Nouveau")).toBeNull();
    expect(screen.getByRole("button", { name: /^Nouvelles \(0\)/ })).toBeInTheDocument();
  });

  it("filters to new dossiers with Nouvelles (count)", async () => {
    const user = userEvent.setup();
    mockBackend({ [WRITABLE_ID]: [NEW_IN_FIRST, CLAIM_TRACKED_WIRE] });
    renderAppAt(WORK(WRITABLE_ID));

    const toggle = await screen.findByRole("button", { name: /^Nouvelles \(1\)/ });
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    await user.click(toggle);

    expect(toggle).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("REF-0001")).toBeInTheDocument();
    expect(screen.queryByText("REF-0002")).toBeNull();
    expect(screen.getByText("1 sur 2 sinistres affichés")).toBeInTheDocument();

    await user.click(toggle);
    expect(screen.getByText("REF-0002")).toBeInTheDocument();
  });

  it("combined with a type, keeps only dossiers new in THAT type", async () => {
    const user = userEvent.setup();
    mockBackend({ [WRITABLE_ID]: [NEW_IN_FIRST, NEW_IN_SECOND] });
    renderAppAt(WORK(WRITABLE_ID));

    await user.click(await screen.findByRole("button", { name: /^Nouvelles \(2\)/ }));
    await user.click(screen.getByRole("button", { name: /^Catégorie test 2 — / }));
    // REF-0001 is in category 2 too, but seen there.
    expect(screen.getByText("REF-0002")).toBeInTheDocument();
    expect(screen.queryByText("REF-0001")).toBeNull();

    await user.click(screen.getByRole("button", { name: /^Catégorie test 1 — / }));
    expect(screen.getByText("REF-0001")).toBeInTheDocument();
    expect(screen.queryByText("REF-0002")).toBeNull();
  });

  it("works from the keyboard", async () => {
    const user = userEvent.setup();
    mockBackend({ [WRITABLE_ID]: [NEW_IN_FIRST, CLAIM_TRACKED_WIRE] });
    renderAppAt(WORK(WRITABLE_ID));

    const toggle = await screen.findByRole("button", { name: /^Nouvelles \(1\)/ });
    toggle.focus();
    await user.keyboard("{Enter}");
    expect(toggle).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByText("REF-0002")).toBeNull();
    await user.keyboard(" ");
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByText("REF-0002")).toBeInTheDocument();
  });

  it("keeps new counts and the filter scoped to the selected account", async () => {
    const user = userEvent.setup();
    mockBackend({
      [WRITABLE_ID]: [NEW_IN_FIRST, NEW_IN_SECOND],
      [READ_ONLY_ID]: [READ_ONLY_CLAIM_WIRE],
    });
    renderAppAt(WORK(WRITABLE_ID));

    await user.click(await screen.findByRole("button", { name: /^Nouvelles \(2\)/ }));
    await user.click(screen.getByRole("link", { name: /MAMDA • ZONE-B/ }));

    // The other account's queue: its own counts, and the filter does not
    // carry over to hide its rows.
    expect(await screen.findByText("REF-0003")).toBeInTheDocument();
    const toggle = screen.getByRole("button", { name: /^Nouvelles \(0\)/ });
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    expect(screen.queryByText("Nouveau")).toBeNull();
    expect(screen.getByRole("button", { name: "Catégorie test 3 — 1 alerte" })).toBeInTheDocument();
  });

  it("never marks anything seen from the list", async () => {
    const stub = mockBackend({ [WRITABLE_ID]: [NEW_IN_FIRST, NEW_IN_SECOND] });
    renderAppAt(WORK(WRITABLE_ID));
    await screen.findByText("REF-0001");

    for (const [, init] of stub.mock.calls as unknown as [string, RequestInit][]) {
      expect(init.method).toBe("GET");
    }
  });
});
