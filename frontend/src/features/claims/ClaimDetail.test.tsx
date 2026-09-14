import { describe, expect, it, vi } from "vitest";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderAppAt } from "../../test/renderApp";
import { mockRoutes, setCsrfCookie } from "../../test/apiMock";
import {
  CLAIM_NEW_WIRE,
  CLAIM_TRACKED_WIRE,
  READ_ONLY_ACCOUNT_WIRE,
  READ_ONLY_CLAIM_WIRE,
  TEST_ACCOUNTS_WIRE,
  WRITABLE_ACCOUNT_CLAIMS_WIRE,
  WRITABLE_ACCOUNT_WIRE,
} from "../../test/fixtures";
import { NOTE_MAX_LENGTH } from "@shared/api/claims";

const WRITABLE_ID = WRITABLE_ACCOUNT_WIRE.account_id;
const READ_ONLY_ID = READ_ONLY_ACCOUNT_WIRE.account_id;

const claimPath = (accountId: string, claimPk: string) =>
  `/accounts/${accountId}/work/${claimPk}`;

function backend(claimsByAccount: Record<string, readonly unknown[]>, actionStatus = 200) {
  return mockRoutes([
    { match: (url) => url.startsWith("/accounts"), body: { accounts: TEST_ACCOUNTS_WIRE } },
    {
      match: (url, init) => url.includes("/action") && init.method === "POST",
      status: actionStatus,
      body:
        actionStatus === 200
          ? { claim_pk: CLAIM_NEW_WIRE.claim_pk, status: "DONE", note: null, version: 2 }
          : { error: "BAD_REQUEST", message: "note is too long (2000 characters maximum)", correlation_id: "0" },
    },
    {
      match: (url) => url.startsWith("/claims"),
      body: (url: string) => ({
        claims:
          claimsByAccount[new URL(url, "http://localhost").searchParams.get("account_id") ?? ""] ??
          [],
      }),
    },
  ]);
}

describe("claim detail resolution", () => {
  it("resolves a claim on a deep link", async () => {
    backend({ [WRITABLE_ID]: WRITABLE_ACCOUNT_CLAIMS_WIRE });
    renderAppAt(claimPath(WRITABLE_ID, CLAIM_NEW_WIRE.claim_pk));

    expect(await screen.findByRole("heading", { name: "REF-0001" })).toBeInTheDocument();
    expect(screen.getByText("Assuré Test Un")).toBeInTheDocument();
    expect(screen.getByText("0000-A-0")).toBeInTheDocument();
  });

  it("fails closed for a claim that is not in the account's list", async () => {
    backend({ [WRITABLE_ID]: WRITABLE_ACCOUNT_CLAIMS_WIRE });
    renderAppAt(claimPath(WRITABLE_ID, "test-claim-absent"));

    expect(await screen.findByText("Ce dossier n'est pas disponible")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Enregistrer le suivi" })).toBeNull();
  });

  it("fails closed for a claim belonging to another account", async () => {
    // The read-only account's claim, requested under the writable account.
    backend({
      [WRITABLE_ID]: WRITABLE_ACCOUNT_CLAIMS_WIRE,
      [READ_ONLY_ID]: [READ_ONLY_CLAIM_WIRE],
    });
    renderAppAt(claimPath(WRITABLE_ID, READ_ONLY_CLAIM_WIRE.claim_pk));

    expect(await screen.findByText("Ce dossier n'est pas disponible")).toBeInTheDocument();
    expect(screen.queryByText("REF-0003")).toBeNull();
  });

  it("never uses the internal identifier as visible identity", async () => {
    backend({ [WRITABLE_ID]: WRITABLE_ACCOUNT_CLAIMS_WIRE });
    renderAppAt(claimPath(WRITABLE_ID, CLAIM_NEW_WIRE.claim_pk));

    await screen.findByRole("heading", { name: "REF-0001" });
    expect(screen.queryByText(CLAIM_NEW_WIRE.claim_pk)).toBeNull();
    expect(screen.queryByText(CLAIM_NEW_WIRE.portal_claim_id)).toBeNull();
  });

  it("formats the tracking timestamp rather than showing the raw value", async () => {
    backend({ [WRITABLE_ID]: [CLAIM_TRACKED_WIRE] });
    renderAppAt(claimPath(WRITABLE_ID, CLAIM_TRACKED_WIRE.claim_pk));

    await screen.findByRole("heading", { name: "REF-0002" });
    expect(screen.queryByText("2026-01-15T09:30:00Z")).toBeNull();
    expect(screen.getByText("Note de suivi test")).toBeInTheDocument();
  });
});

describe("tracking editor", () => {
  it("saves a status and refetches the authoritative claims", async () => {
    setCsrfCookie();
    const stub = backend({ [WRITABLE_ID]: WRITABLE_ACCOUNT_CLAIMS_WIRE });
    const user = userEvent.setup();
    renderAppAt(claimPath(WRITABLE_ID, CLAIM_NEW_WIRE.claim_pk));

    await screen.findByRole("heading", { name: "REF-0001" });
    const claimsBefore = stub.mock.calls.filter(([url]) =>
      (url as string).startsWith("/claims?"),
    ).length;

    await user.selectOptions(screen.getByLabelText("Statut"), "DONE");
    await user.click(screen.getByRole("button", { name: "Enregistrer le suivi" }));

    await waitFor(() => {
      const posted = stub.mock.calls.find(
        ([, init]) => (init as RequestInit | undefined)?.method === "POST",
      );
      expect(posted).toBeDefined();
      expect(JSON.parse((posted?.[1] as RequestInit).body as string)).toEqual({
        status: "DONE",
        note: null,
      });
    });

    // The list is refetched rather than patched locally.
    await waitFor(() => {
      const claimsAfter = stub.mock.calls.filter(([url]) =>
        (url as string).startsWith("/claims?"),
      ).length;
      expect(claimsAfter).toBeGreaterThan(claimsBefore);
    });
  });

  it("sends a note the employee typed", async () => {
    setCsrfCookie();
    const stub = backend({ [WRITABLE_ID]: WRITABLE_ACCOUNT_CLAIMS_WIRE });
    const user = userEvent.setup();
    renderAppAt(claimPath(WRITABLE_ID, CLAIM_NEW_WIRE.claim_pk));

    await screen.findByRole("heading", { name: "REF-0001" });
    await user.type(screen.getByLabelText("Note"), "Relance faite");
    await user.click(screen.getByRole("button", { name: "Enregistrer le suivi" }));

    await waitFor(() => {
      const posted = stub.mock.calls.find(
        ([, init]) => (init as RequestInit | undefined)?.method === "POST",
      );
      expect(JSON.parse((posted?.[1] as RequestInit).body as string).note).toBe("Relance faite");
    });
  });

  it("blocks a note over the backend limit before any request", async () => {
    setCsrfCookie();
    const stub = backend({ [WRITABLE_ID]: WRITABLE_ACCOUNT_CLAIMS_WIRE });
    renderAppAt(claimPath(WRITABLE_ID, CLAIM_NEW_WIRE.claim_pk));

    await screen.findByRole("heading", { name: "REF-0001" });
    const note = screen.getByLabelText("Note") as HTMLTextAreaElement;
    // Typing 2001 characters one keystroke at a time is far too slow; the
    // change handler is what the component actually listens to.
    note.focus();
    const tooLong = "n".repeat(NOTE_MAX_LENGTH + 1);
    const setter = Object.getOwnPropertyDescriptor(
      HTMLTextAreaElement.prototype,
      "value",
    )?.set;
    act(() => {
      setter?.call(note, tooLong);
      note.dispatchEvent(new Event("input", { bubbles: true }));
    });

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Enregistrer le suivi" })).toBeDisabled(),
    );
    expect(screen.getByText(/1 caractères de trop/)).toBeInTheDocument();
    expect(
      stub.mock.calls.some(([, init]) => (init as RequestInit | undefined)?.method === "POST"),
    ).toBe(false);
  });

  it("keeps the draft and hides the raw message when the backend refuses", async () => {
    setCsrfCookie();
    backend({ [WRITABLE_ID]: WRITABLE_ACCOUNT_CLAIMS_WIRE }, 400);
    const user = userEvent.setup();
    renderAppAt(claimPath(WRITABLE_ID, CLAIM_NEW_WIRE.claim_pk));

    await screen.findByRole("heading", { name: "REF-0001" });
    await user.type(screen.getByLabelText("Note"), "Brouillon à conserver");
    await user.click(screen.getByRole("button", { name: "Enregistrer le suivi" }));

    await screen.findByRole("alert");
    // The employee does not lose what they wrote.
    expect(screen.getByLabelText("Note")).toHaveValue("Brouillon à conserver");
    expect(screen.queryByText(/2000 characters maximum/)).toBeNull();
  });

  it("tracks a MAMDA claim, which is read-only for automation only", async () => {
    setCsrfCookie();
    const stub = backend({ [READ_ONLY_ID]: [READ_ONLY_CLAIM_WIRE] });
    const user = userEvent.setup();
    renderAppAt(claimPath(READ_ONLY_ID, READ_ONLY_CLAIM_WIRE.claim_pk));

    await screen.findByRole("heading", { name: "REF-0003" });
    expect(screen.getAllByText("Lecture seule").length).toBeGreaterThan(0);

    await user.selectOptions(screen.getByLabelText("Statut"), "IN_PROGRESS");
    await user.click(screen.getByRole("button", { name: "Enregistrer le suivi" }));

    await waitFor(() => {
      const posted = stub.mock.calls.find(
        ([, init]) => (init as RequestInit | undefined)?.method === "POST",
      );
      expect(posted?.[0]).toBe(`/claims/${READ_ONLY_CLAIM_WIRE.claim_pk}/action`);
    });
  });

  it("triggers no portal automation and offers no portal action", async () => {
    setCsrfCookie();
    const stub = backend({ [WRITABLE_ID]: WRITABLE_ACCOUNT_CLAIMS_WIRE });
    const user = userEvent.setup();
    renderAppAt(claimPath(WRITABLE_ID, CLAIM_NEW_WIRE.claim_pk));

    await screen.findByRole("heading", { name: "REF-0001" });
    await user.click(screen.getByRole("button", { name: "Enregistrer le suivi" }));

    await waitFor(() =>
      expect(
        stub.mock.calls.some(([, init]) => (init as RequestInit | undefined)?.method === "POST"),
      ).toBe(true),
    );
    // Tracking a claim creates no automation job. The shell's own GET /jobs
    // read for the active-run banner is not a job creation.
    expect(
      stub.mock.calls.some(
        ([url, init]) =>
          (url as string).startsWith("/jobs") &&
          (init as RequestInit | undefined)?.method === "POST",
      ),
    ).toBe(false);
    for (const forbidden of ["Valider", "Clôturer", "Enregistrer SinAuto", "Finaliser"]) {
      expect(screen.queryByRole("button", { name: new RegExp(forbidden) })).toBeNull();
    }
  });
});

describe("draft state does not cross claims", () => {
  it("shows the new claim's own status and note after navigating", async () => {
    setCsrfCookie();
    const user = userEvent.setup();
    const stub = backend({ [WRITABLE_ID]: WRITABLE_ACCOUNT_CLAIMS_WIRE });

    const first = renderAppAt(claimPath(WRITABLE_ID, CLAIM_NEW_WIRE.claim_pk));
    await screen.findByRole("heading", { name: "REF-0001" });
    await user.type(screen.getByLabelText("Note"), "note-a");
    expect(screen.getByLabelText("Note")).toHaveValue("note-a");
    first.unmount();

    // A different claim: its own authoritative status and note, never the
    // draft left behind on the previous one.
    renderAppAt(claimPath(WRITABLE_ID, CLAIM_TRACKED_WIRE.claim_pk));
    await screen.findByRole("heading", { name: "REF-0002" });
    expect(screen.getByLabelText("Note")).toHaveValue("Note de suivi test");
    expect(screen.getByLabelText("Note")).not.toHaveValue("note-a");
    expect(screen.getByLabelText("Statut")).toHaveValue("IN_PROGRESS");

    await user.click(screen.getByRole("button", { name: "Enregistrer le suivi" }));
    await waitFor(() => {
      const posted = stub.mock.calls.find(
        ([, init]) => (init as RequestInit | undefined)?.method === "POST",
      );
      const body = JSON.parse((posted?.[1] as RequestInit).body as string) as { note: string };
      expect(posted?.[0]).toBe(`/claims/${CLAIM_TRACKED_WIRE.claim_pk}/action`);
      expect(body.note).not.toBe("note-a");
      expect(body.note).toBe("Note de suivi test");
    });
  });
});

describe("opening a dossier marks its notifications seen", () => {
  const UNREAD_CLAIM_WIRE = {
    ...CLAIM_NEW_WIRE,
    notifications: [
      { category: "Catégorie test 1", unread: true, appeared_at: "2026-02-01T08:00:00Z", seen_at: null },
      { category: "Catégorie test 2", unread: false, appeared_at: null, seen_at: null },
    ],
  };

  /** Reports the notification unread until the mark-seen POST succeeds. */
  function freshnessBackend(seenStatus = 200) {
    let seen = false;
    return mockRoutes([
      { match: (url) => url.startsWith("/accounts"), body: { accounts: TEST_ACCOUNTS_WIRE } },
      {
        match: (url, init) => url.endsWith("/notifications/seen") && init.method === "POST",
        status: seenStatus,
        body: () => {
          if (seenStatus !== 200) {
            return { error: "FORBIDDEN", message: "insufficient permission", correlation_id: "0" };
          }
          seen = true;
          return { claim_pk: CLAIM_NEW_WIRE.claim_pk, marked_seen: 1 };
        },
      },
      {
        match: (url) => url.startsWith("/claims"),
        body: () => ({ claims: [seen ? CLAIM_NEW_WIRE : UNREAD_CLAIM_WIRE, CLAIM_TRACKED_WIRE] }),
      },
    ]);
  }

  const calls = (stub: ReturnType<typeof mockRoutes>) =>
    stub.mock.calls as unknown as [string, RequestInit | undefined][];
  const seenPosts = (stub: ReturnType<typeof mockRoutes>) =>
    calls(stub).filter(([url, init]) => url.endsWith("/notifications/seen") && init?.method === "POST");

  it("posts once, without an account id, then refetches the server-confirmed list", async () => {
    setCsrfCookie();
    const stub = freshnessBackend();
    const user = userEvent.setup();
    renderAppAt(claimPath(WRITABLE_ID, CLAIM_NEW_WIRE.claim_pk));

    await screen.findByRole("heading", { name: "REF-0001" });
    await waitFor(() => expect(seenPosts(stub)).toHaveLength(1));
    const [path, init] = seenPosts(stub)[0] as [string, RequestInit];
    expect(path).toBe(`/claims/${CLAIM_NEW_WIRE.claim_pk}/notifications/seen`);
    expect(init.body).toBeUndefined();

    // The list is refetched after the POST, not patched locally.
    const postIndex = calls(stub).findIndex(([url]) => url.endsWith("/notifications/seen"));
    await waitFor(() =>
      expect(calls(stub).slice(postIndex + 1).some(([url]) => url.startsWith("/claims?"))).toBe(true),
    );

    // Back on the list, the dossier is no longer new -- because the backend said so.
    await user.click(screen.getByRole("link", { name: /Revenir à la file de travail/ }));
    const row = (await screen.findByRole("link", { name: "REF-0001" })).closest("tr") as HTMLElement;
    await waitFor(() => expect(within(row).queryByText("Nouveau")).toBeNull());

    // Once only, and the tracking status was never written.
    expect(seenPosts(stub)).toHaveLength(1);
    expect(calls(stub).some(([url]) => url.includes("/action"))).toBe(false);
  });

  it("sends nothing when no notification on the dossier is new", async () => {
    setCsrfCookie();
    const stub = backend({ [WRITABLE_ID]: WRITABLE_ACCOUNT_CLAIMS_WIRE });
    renderAppAt(claimPath(WRITABLE_ID, CLAIM_NEW_WIRE.claim_pk));

    await screen.findByRole("heading", { name: "REF-0001" });
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(calls(stub).some(([, init]) => init?.method === "POST")).toBe(false);
  });

  it("keeps the notification new when the backend refuses, and does not retry", async () => {
    setCsrfCookie();
    const stub = freshnessBackend(403);
    const user = userEvent.setup();
    renderAppAt(claimPath(WRITABLE_ID, CLAIM_NEW_WIRE.claim_pk));

    await screen.findByRole("heading", { name: "REF-0001" });
    expect(
      await screen.findByText(/n'ont pas pu être marquées comme vues/),
    ).toBeInTheDocument();
    expect(screen.queryByText("insufficient permission")).toBeNull();

    await user.click(screen.getByRole("link", { name: /Revenir à la file de travail/ }));
    const row = (await screen.findByRole("link", { name: "REF-0001" })).closest("tr") as HTMLElement;
    expect(within(row).getByText("Nouveau")).toBeInTheDocument();
    expect(seenPosts(stub)).toHaveLength(1);
  });
});

describe("privacy", () => {
  it("logs nothing while showing and saving a claim", async () => {
    setCsrfCookie();
    const log = vi.spyOn(console, "log").mockImplementation(() => {});
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    backend({ [WRITABLE_ID]: WRITABLE_ACCOUNT_CLAIMS_WIRE });
    const user = userEvent.setup();
    renderAppAt(claimPath(WRITABLE_ID, CLAIM_NEW_WIRE.claim_pk));

    await screen.findByRole("heading", { name: "REF-0001" });
    await user.click(screen.getByRole("button", { name: "Enregistrer le suivi" }));

    expect(log).not.toHaveBeenCalled();
    expect(warn).not.toHaveBeenCalled();
  });
});

describe("feedback after marking notifications seen", () => {
  const UNREAD_WIRE = {
    ...CLAIM_NEW_WIRE,
    notifications: [
      { category: "Catégorie test 1", unread: true, appeared_at: "2026-02-01T08:00:00Z", seen_at: null },
    ],
  };

  const jsonResponse = (body: unknown, status = 200) =>
    ({
      ok: status < 400,
      status,
      text: () => Promise.resolve(JSON.stringify(body)),
    }) as unknown as Response;

  /**
   * A backend whose mark-seen response is held open until released, so the
   * window between "request sent" and "backend confirmed" can be asserted on.
   */
  function heldBackend(seenStatus = 200) {
    let release: () => void = () => {};
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    let seen = false;

    const stub = vi.fn(async (url: string, init: RequestInit = {}) => {
      if (url.startsWith("/accounts")) return jsonResponse({ accounts: TEST_ACCOUNTS_WIRE });
      if (url.endsWith("/notifications/seen") && init.method === "POST") {
        await held;
        if (seenStatus >= 400) {
          return jsonResponse(
            { error: "FORBIDDEN", message: "insufficient permission", correlation_id: "0" },
            seenStatus,
          );
        }
        seen = true;
        return jsonResponse({ claim_pk: CLAIM_NEW_WIRE.claim_pk, marked_seen: 1 });
      }
      return jsonResponse({ claims: [seen ? CLAIM_NEW_WIRE : UNREAD_WIRE] });
    });
    vi.stubGlobal("fetch", stub);
    return { stub, release: () => release() };
  }

  const seenPosts = (stub: ReturnType<typeof vi.fn>) =>
    (stub.mock.calls as unknown as [string, RequestInit | undefined][]).filter(
      ([url, init]) => url.endsWith("/notifications/seen") && init?.method === "POST",
    );

  it("confirms only once the backend has confirmed", async () => {
    setCsrfCookie();
    const { stub, release } = heldBackend();
    renderAppAt(claimPath(WRITABLE_ID, CLAIM_NEW_WIRE.claim_pk));

    await screen.findByRole("heading", { name: "REF-0001" });
    // The request is in flight and unanswered: nothing may claim success yet.
    await waitFor(() => expect(seenPosts(stub)).toHaveLength(1));
    expect(screen.queryByText("Notifications marquées comme vues.")).toBeNull();

    release();

    expect(await screen.findByText("Notifications marquées comme vues.")).toBeInTheDocument();
  });

  it("shows no confirmation when the backend refuses, and says so instead", async () => {
    setCsrfCookie();
    const { stub, release } = heldBackend(403);
    renderAppAt(claimPath(WRITABLE_ID, CLAIM_NEW_WIRE.claim_pk));

    await screen.findByRole("heading", { name: "REF-0001" });
    await waitFor(() => expect(seenPosts(stub)).toHaveLength(1));
    release();

    expect(
      await screen.findByText(/n'ont pas pu être marquées comme vues/),
    ).toBeInTheDocument();
    expect(screen.queryByText("Notifications marquées comme vues.")).toBeNull();
    // The raw backend wording never reaches the employee.
    expect(screen.queryByText(/insufficient permission/)).toBeNull();
  });

  it("stays quiet when the dossier had nothing new to mark", async () => {
    setCsrfCookie();
    backend({ [WRITABLE_ID]: WRITABLE_ACCOUNT_CLAIMS_WIRE });
    renderAppAt(claimPath(WRITABLE_ID, CLAIM_NEW_WIRE.claim_pk));

    await screen.findByRole("heading", { name: "REF-0001" });
    expect(screen.queryByText("Notifications marquées comme vues.")).toBeNull();
  });
});

describe("marking seen refreshes the account summaries", () => {
  const UNREAD_WIRE = {
    ...CLAIM_NEW_WIRE,
    notifications: [
      { category: "Catégorie test 1", unread: true, appeared_at: "2026-02-01T08:00:00Z", seen_at: null },
      { category: "Catégorie test 2", unread: true, appeared_at: "2026-02-01T08:00:00Z", seen_at: null },
    ],
  };

  const json = (body: unknown) =>
    ({ ok: true, status: 200, text: () => Promise.resolve(JSON.stringify(body)) }) as unknown as Response;

  /**
   * One backend for the whole shell, whose /accounts answer changes once the
   * dossier's notifications have been marked seen -- exactly as the real one
   * does, since both the summary and the claim list are derived from the same
   * category_presence rows.
   */
  function backendWhereSeenClearsTheBadge() {
    let seen = false;
    const stub = vi.fn(async (url: string, init: RequestInit = {}) => {
      if (url.startsWith("/accounts")) {
        return json({
          accounts: TEST_ACCOUNTS_WIRE.map((account) =>
            account.account_id === WRITABLE_ID
              ? {
                  ...account,
                  unread_notification_count: seen ? 0 : 2,
                  unread_claim_count: seen ? 0 : 1,
                }
              : account,
          ),
        });
      }
      if (url.endsWith("/notifications/seen") && init.method === "POST") {
        seen = true;
        return json({ claim_pk: CLAIM_NEW_WIRE.claim_pk, marked_seen: 2 });
      }
      if (url.startsWith("/jobs")) return json({ jobs: [] });
      return json({ claims: [seen ? CLAIM_NEW_WIRE : UNREAD_WIRE] });
    });
    vi.stubGlobal("fetch", stub);
    return stub;
  }

  const accountReads = (stub: ReturnType<typeof vi.fn>) =>
    (stub.mock.calls as unknown as [string, RequestInit | undefined][]).filter(([url]) =>
      url.startsWith("/accounts"),
    ).length;

  it("clears the sidebar unread badge after the backend confirms", async () => {
    setCsrfCookie();
    const stub = backendWhereSeenClearsTheBadge();
    renderAppAt(claimPath(WRITABLE_ID, CLAIM_NEW_WIRE.claim_pk));

    const rail = screen.getByRole("navigation", { name: "Comptes portail" });
    // Before: the rail carries this account's two new notifications.
    expect(
      await within(rail).findByRole("link", {
        name: /2 nouvelles notifications, 1 dossier concerné/,
      }),
    ).toBeInTheDocument();
    const readsBefore = accountReads(stub);

    // After: the badge is gone because /accounts was asked again and said so,
    // not because the browser assumed it.
    await waitFor(() =>
      expect(within(rail).queryByRole("link", { name: /nouvelles? notifications?/ })).toBeNull(),
    );
    expect(accountReads(stub)).toBeGreaterThan(readsBefore);
  });

  it("leaves the other accounts' badges alone", async () => {
    setCsrfCookie();
    backendWhereSeenClearsTheBadge();
    renderAppAt(claimPath(WRITABLE_ID, CLAIM_NEW_WIRE.claim_pk));

    const rail = screen.getByRole("navigation", { name: "Comptes portail" });
    await within(rail).findByRole("link", { name: /2 nouvelles notifications/ });
    await waitFor(() =>
      expect(within(rail).queryByRole("link", { name: /nouvelles? notifications?/ })).toBeNull(),
    );

    // The read-only and second writable accounts never had a badge and still
    // render normally -- one account's mark-seen is not a global reset.
    expect(within(rail).getByText("MAMDA • ZONE-B")).toBeInTheDocument();
    expect(within(rail).getByText("MCMA • ZONE-C")).toBeInTheDocument();
  });

  it("does not re-read the account list when there was nothing to mark", async () => {
    setCsrfCookie();
    const stub = vi.fn(async (url: string) => {
      if (url.startsWith("/accounts")) return json({ accounts: TEST_ACCOUNTS_WIRE });
      if (url.startsWith("/jobs")) return json({ jobs: [] });
      return json({ claims: [CLAIM_NEW_WIRE] });
    });
    vi.stubGlobal("fetch", stub);

    renderAppAt(claimPath(WRITABLE_ID, CLAIM_NEW_WIRE.claim_pk));
    await screen.findByRole("heading", { name: "REF-0001" });
    const reads = accountReads(stub);
    await new Promise((resolve) => setTimeout(resolve, 20));

    expect(accountReads(stub)).toBe(reads);
  });
});
