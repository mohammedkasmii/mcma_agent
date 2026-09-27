import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockRoutes } from "../../test/apiMock";
import type { RouteHandler } from "../../test/apiMock";
import { TEST_ACCOUNTS_WIRE, WRITABLE_ACCOUNT_WIRE } from "../../test/fixtures";
import { renderAppAt, TEST_SESSION } from "../../test/renderApp";
import type { AccountWire } from "@shared/api/wire";

afterEach(() => {
  vi.useRealTimers();
});

function accountWith(accountId: string): AccountWire {
  return { ...WRITABLE_ACCOUNT_WIRE, account_id: accountId };
}

function backend(runnerStatus: unknown, accountId: string, extra: readonly RouteHandler[] = []) {
  return mockRoutes([
    ...extra,
    { match: (url) => url === "/runner-status", body: runnerStatus },
    { match: (url) => url.startsWith("/accounts"), body: { accounts: [accountWith(accountId), ...TEST_ACCOUNTS_WIRE.slice(1)] } },
    { match: (url) => url.startsWith("/claims"), body: { claims: [] } },
    { match: (url) => url.startsWith("/jobs"), body: { jobs: [] } },
  ]);
}

const status = (state: string, sessions: unknown[] = []) => ({
  status: state,
  runner_label: null,
  last_seen_at: null,
  protocol_version: null,
  sessions,
});

const AGENT = (id: string) => `/accounts/${id}/agent`;

describe("agent screen runner panel", () => {
  it.each([
    ["UNPAIRED", "Poste agent non associé"],
    ["OFFLINE", "Poste agent hors ligne"],
    ["REVOKED", "Poste agent révoqué"],
  ])("shows %s", async (state, text) => {
    backend(status(state), "acct-mcma-oujda");
    renderAppAt(AGENT("acct-mcma-oujda"));
    expect(await screen.findByText(text)).toBeInTheDocument();
    expect(screen.queryByText(/Connexion MCMA/)).toBeNull();
  });

  it.each([
    ["acct-mcma-oujda", "LOGIN_REQUIRED", "Connexion MCMA Oujda requise"],
    ["acct-mcma-oujda", "NOT_CONFIGURED", "Connexion MCMA Oujda requise"],
    ["acct-mcma-nador", "LOGIN_REQUIRED", "Connexion MCMA Nador requise"],
    ["acct-mcma-nador", "ERROR", "Erreur de session MCMA Nador"],
    ["acct-mcma-oujda", "ERROR", "Erreur de session MCMA Oujda"],
  ])("online, %s %s -> %s", async (accountId, state, sentence) => {
    backend(status("ONLINE", [{ account_id: accountId, state }]), accountId);
    renderAppAt(AGENT(accountId));
    expect(await screen.findByText("Poste agent connecté")).toBeInTheDocument();
    expect(screen.getByText(sentence)).toBeInTheDocument();
  });

  it("online with a missing session counts as not configured", async () => {
    backend(status("ONLINE", []), "acct-mcma-nador");
    renderAppAt(AGENT("acct-mcma-nador"));
    expect(await screen.findByText("Connexion MCMA Nador requise")).toBeInTheDocument();
  });

  it("shows Prêt for the viewed account only", async () => {
    backend(
      status("ONLINE", [
        { account_id: "acct-mcma-oujda", state: "READY" },
        { account_id: "acct-mcma-nador", state: "LOGIN_REQUIRED" },
      ]),
      "acct-mcma-oujda",
    );
    renderAppAt(AGENT("acct-mcma-oujda"));
    expect(await screen.findByText("Prêt")).toBeInTheDocument();
    expect(screen.queryByText(/Nador/)).toBeNull();
  });

  it("does not change the submit behaviour: it stays governed by the chosen file", async () => {
    backend(status("OFFLINE"), "acct-mcma-oujda");
    renderAppAt(AGENT("acct-mcma-oujda"));
    await screen.findByText("Poste agent hors ligne");
    expect(screen.getByRole("button", { name: "Préparer le plan" })).toBeDisabled();
  });

  it("reports an unavailable status quietly", async () => {
    mockRoutes([
      { match: (url) => url.startsWith("/accounts"), body: { accounts: TEST_ACCOUNTS_WIRE } },
    ]);
    renderAppAt(AGENT(WRITABLE_ACCOUNT_WIRE.account_id));
    expect(await screen.findByText("Statut du poste agent indisponible.")).toBeInTheDocument();
  });

  it("polls only /runner-status (about every 15s) and adds no other polling", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const stub = backend(status("OFFLINE"), "acct-mcma-oujda");
    const view = renderAppAt(AGENT("acct-mcma-oujda"));
    await screen.findByText("Poste agent hors ligne");

    const urls = () => stub.mock.calls.map(([url]) => url as string);
    const statusCalls = () => urls().filter((url) => url === "/runner-status").length;
    const others = () => urls().filter((url) => url !== "/runner-status");
    const otherBefore = others();
    const before = statusCalls();

    await vi.advanceTimersByTimeAsync(15_500);
    expect(statusCalls()).toBe(before + 1);
    expect(others()).toEqual(otherBefore);

    view.unmount();
    const after = statusCalls();
    await vi.advanceTimersByTimeAsync(60_000);
    expect(statusCalls()).toBe(after);
  });

  it("local single-user mode: no runner panel, /runner-status is never requested, even after timers", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const stub = backend(status("ONLINE"), "acct-mcma-oujda");
    const view = renderAppAt(AGENT("acct-mcma-oujda"), undefined, {
      auth: { ...TEST_SESSION, role: "operator", localSingleUser: true },
    });
    // The rest of the Agent screen is there ...
    await vi.waitFor(() => expect(document.body.textContent).toContain("Nouveau run"));
    // ... but the runner panel is absent.
    expect(screen.queryByText(/Poste agent/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Statut du poste agent/)).not.toBeInTheDocument();

    const runnerCalls = () => stub.mock.calls.filter(([url]) => String(url).includes("runner-status")).length;
    expect(runnerCalls()).toBe(0);
    await vi.advanceTimersByTimeAsync(60_000);              // four polling periods
    expect(runnerCalls()).toBe(0);
    view.unmount();
    await vi.advanceTimersByTimeAsync(30_000);
    expect(runnerCalls()).toBe(0);
  });

  it("central mode (localSingleUser false) keeps the panel and its 15 s polling", async () => {
    backend(status("OFFLINE"), "acct-mcma-oujda");
    renderAppAt(AGENT("acct-mcma-oujda"), undefined, { auth: { ...TEST_SESSION, localSingleUser: false } });
    expect(await screen.findByText("Poste agent hors ligne")).toBeInTheDocument();
  });
});
