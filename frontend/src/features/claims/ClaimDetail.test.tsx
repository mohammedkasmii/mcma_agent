import { describe, expect, it, vi } from "vitest";
import { act, screen, waitFor } from "@testing-library/react";
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
