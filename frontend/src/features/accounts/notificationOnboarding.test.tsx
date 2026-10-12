import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderAppAt } from "../../test/renderApp";
import { mockRoutes, setCsrfCookie } from "../../test/apiMock";
import { WRITABLE_ACCOUNT_WIRE } from "../../test/fixtures";

const ID = WRITABLE_ACCOUNT_WIRE.account_id;

function view(state: string, outcome: string | null = null, extra: Record<string, unknown> = {}) {
  return {
    account_id: ID,
    request_id: "a".repeat(32),
    state,
    outcome_code: outcome,
    cancel_requested: false,
    expires_at: "2030-01-01T00:05:00+00:00",
    updated_at: "2030-01-01T00:00:00+00:00",
    ...extra,
  };
}

interface Script {
  postStatus?: number;
  postBody?: unknown;
  statuses: unknown[]; // successive GET login-status answers; the last repeats
  connectedAfterSuccess?: boolean;
}

function backend(script: Script) {
  let polls = 0;
  let succeeded = false;
  return mockRoutes([
    {
      match: (url, init) => url === `/accounts/${ID}/login` && init.method === "POST",
      status: script.postStatus ?? 202,
      body: script.postBody ?? view("QUEUED"),
    },
    {
      match: (url, init) => url === `/accounts/${ID}/login/cancel` && init.method === "POST",
      body: view("CANCELLED", "CANCELLED_BY_USER"),
    },
    {
      match: (url) => url === `/accounts/${ID}/login-status`,
      body: () => {
        const body = script.statuses[Math.min(polls, script.statuses.length - 1)] as { state: string };
        polls += 1;
        if (body.state === "SUCCEEDED") succeeded = true;
        return body;
      },
    },
    {
      match: (url) => url.startsWith("/accounts"),
      body: () => ({
        accounts: [
          {
            ...WRITABLE_ACCOUNT_WIRE,
            connection_state: succeeded && script.connectedAfterSuccess ? "CONNECTED" : "NOT_CONNECTED",
          },
        ],
      }),
    },
    { match: (url) => url.startsWith("/claims"), body: { claims: [] } },
    { match: (url) => url.startsWith("/jobs"), body: { jobs: [] } },
  ]);
}

const calls = (stub: ReturnType<typeof vi.fn>, suffix: string) =>
  stub.mock.calls.filter(([url]) => (url as string).endsWith(suffix)).length;

const accountListFetches = (stub: ReturnType<typeof vi.fn>) =>
  stub.mock.calls.filter(
    ([url, init]) =>
      url === "/accounts" && ((init as RequestInit | undefined)?.method ?? "GET") === "GET",
  ).length;

beforeEach(() => {
  setCsrfCookie();
  vi.useFakeTimers({ shouldAdvanceTime: true });
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

async function clickConnect() {
  const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
  renderAppAt("/overview");
  await user.click(await screen.findByRole("button", { name: "Se connecter" }));
  return user;
}

const tick = (ms = 2000) =>
  act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });

describe("central notification onboarding", () => {
  it("shows queued, then window opened, then waiting for login/OTP", async () => {
    backend({
      statuses: [view("QUEUED"), view("OPENING_WINDOW"), view("WINDOW_OPENED"), view("WAITING_FOR_LOGIN")],
    });
    await clickConnect();
    expect(await screen.findByText(/en attente du poste de travail/i)).toBeInTheDocument();
    await tick();
    expect(await screen.findByText(/Ouverture de la fenêtre de connexion sur votre poste/i)).toBeInTheDocument();
    await tick();
    expect(await screen.findByText(/fenêtre de connexion SinAuto est ouverte/i)).toBeInTheDocument();
    await tick();
    expect(await screen.findByText(/saisissez vos identifiants et le code OTP/i)).toBeInTheDocument();
  });

  it("disables the button while active, so a second click cannot queue a second request", async () => {
    const stub = backend({ statuses: [view("WAITING_FOR_LOGIN")] });
    const user = await clickConnect();
    const button = await screen.findByRole("button", { name: /Connexion…|Se connecter/ });
    expect(button).toBeDisabled();
    await user.click(button);
    const posts = stub.mock.calls.filter(
      ([url, init]) => url === `/accounts/${ID}/login` && (init as RequestInit).method === "POST",
    );
    expect(posts).toHaveLength(1);
  });

  it("confirms success only after the server says SUCCEEDED, then refetches the accounts", async () => {
    const stub = backend({
      statuses: [view("QUEUED"), view("WAITING_FOR_LOGIN"), view("SUCCEEDED", "SESSION_STORED")],
      connectedAfterSuccess: true,
    });
    await clickConnect();
    await tick();
    expect(screen.queryByText(/compte est connecté/i)).toBeNull();
    const before = accountListFetches(stub);
    await tick();
    expect(await screen.findByText(/compte est connecté/i)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "Actualiser" })).toBeInTheDocument());
    expect(accountListFetches(stub)).toBeGreaterThan(before);
  });

  it("stops polling once a terminal state is reached", async () => {
    const stub = backend({ statuses: [view("FAILED", "LOGIN_TIMED_OUT")] });
    await clickConnect();
    await tick();
    expect(await screen.findByText(/délai de connexion dépassé/i)).toBeInTheDocument();
    const settled = calls(stub, "/login-status");
    await tick(10000);
    expect(calls(stub, "/login-status")).toBe(settled);
    expect(screen.getByRole("button", { name: "Se connecter" })).toBeEnabled();
  });

  it("stops polling when the control unmounts", async () => {
    const stub = backend({ statuses: [view("WAITING_FOR_LOGIN")] });
    await clickConnect();
    await tick();
    const n = calls(stub, "/login-status");
    expect(n).toBeGreaterThan(0);
    cleanup();
    await tick(10000);
    expect(calls(stub, "/login-status")).toBe(n);
  });

  it.each([
    ["FAILED", "LOGIN_WINDOW_CLOSED", /fenêtre de connexion a été fermée/i],
    ["FAILED", "INTERNAL_ERROR", /erreur interne/i],
    ["EXPIRED", "REQUEST_EXPIRED", /demande a expiré/i],
    ["EXPIRED", "LEASE_EXPIRED", /demande a expiré/i],
    ["CANCELLED", "CANCELLED_BY_USER", /connexion annulée/i],
    ["FAILED", "RUNNER_BUSY", /poste de travail est occupé/i],
  ])("renders %s/%s with a specific French message", async (state, outcome, pattern) => {
    backend({ postBody: view("QUEUED"), statuses: [view(state, outcome)] });
    await clickConnect();
    await tick();
    expect(await screen.findByText(pattern)).toBeInTheDocument();
    expect(screen.queryByText(/L'action n'a pas abouti/)).toBeNull();
  });

  it.each([
    ["RUNNER_OFFLINE", /poste de travail est hors ligne/i],
    ["RUNNER_MISSING", /aucun poste de travail actif/i],
    ["RUNNER_BUSY", /poste de travail est occupé/i],
  ])("maps the %s refusal to a specific message", async (code, pattern) => {
    backend({
      postStatus: 409,
      postBody: { error: code, message: "x", correlation_id: "0" },
      statuses: [view("IDLE")],
    });
    await clickConnect();
    expect(await screen.findByText(pattern)).toBeInTheDocument();
    expect(screen.queryByText(/L'action n'a pas abouti/)).toBeNull();
  });

  it("offers Annuler while active and posts the cancel", async () => {
    const stub = backend({ statuses: [view("WAITING_FOR_LOGIN")] });
    const user = await clickConnect();
    await user.click(await screen.findByRole("button", { name: "Annuler" }));
    await waitFor(() => expect(calls(stub, "/login/cancel")).toBe(1));
    expect(await screen.findByText(/connexion annulée/i)).toBeInTheDocument();
  });

  it("keeps the local synchronous behaviour when the answer has no state", async () => {
    const stub = backend({
      postStatus: 200,
      postBody: { account_id: ID, session_id: "s" },
      statuses: [view("IDLE")],
    });
    await clickConnect();
    await waitFor(() => expect(screen.getByRole("button", { name: "Se connecter" })).toBeEnabled());
    expect(calls(stub, "/login-status")).toBe(0);
  });
});
