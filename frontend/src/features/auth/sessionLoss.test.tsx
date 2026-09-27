import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { installControllableEventSource, mockAuthBackend } from "../../test/authMock";
import type { AuthBackend } from "../../test/authMock";
import { createTestQueryClient, renderAppAt } from "../../test/renderApp";

const COOLDOWN = 150;
const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

async function start() {
  const events = installControllableEventSource();
  const backend = mockAuthBackend({ signedIn: true });
  const queryClient = createTestQueryClient();
  const view = renderAppAt("/overview", queryClient, {
    auth: "probe",
    recheckCooldownMs: COOLDOWN,
  });
  await screen.findByRole("heading", { name: "Vue d'ensemble" });
  await waitFor(() => expect(events.instances).toHaveLength(1));
  return { events, backend, queryClient, view, source: () => events.instances.at(-1)! };
}

const meCalls = (backend: AuthBackend) => backend.calls("/auth/me");

describe("session loss over the event stream", () => {
  it("an error plus a 401 from /auth/me expires the session", async () => {
    const { events, backend, queryClient, view, source } = await start();
    const first = source();
    backend.expire();
    act(() => first.emit("error", { closed: true }));

    expect(
      await screen.findByText("Votre session a expiré. Veuillez vous reconnecter."),
    ).toBeInTheDocument();
    expect(view.router.state.location.pathname).toBe("/login");
    expect(queryClient.getQueryCache().getAll()).toHaveLength(0);
    expect(first.closed).toBe(true);
    expect(events.live).toBe(0);
    expect(backend.calls("/auth/logout")).toBe(0);
  });

  it("an error while /auth/me is unreachable keeps the user signed in", async () => {
    const { backend, source, view } = await start();
    const original = backend.stub.getMockImplementation();
    backend.stub.mockImplementation((url: string, init: RequestInit) =>
      url === "/auth/me" ? Promise.reject(new TypeError("down")) : original?.(url, init),
    );
    const before = meCalls(backend);
    act(() => source().emit("error"));

    await waitFor(() => expect(meCalls(backend)).toBe(before + 1));
    await sleep(30);
    expect(view.router.state.location.pathname).toBe("/overview");
    expect(screen.queryByText(/Votre session a expiré/)).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("recovers from a server restart without any click", async () => {
    const { backend, source, view } = await start();
    const original = backend.stub.getMockImplementation();
    backend.stub.mockImplementation((url: string, init: RequestInit) =>
      url === "/auth/me" ? Promise.reject(new TypeError("down")) : original?.(url, init),
    );
    const before = meCalls(backend);
    act(() => source().emit("error"));
    await waitFor(() => expect(meCalls(backend)).toBe(before + 1));
    await sleep(20);
    expect(view.router.state.location.pathname).toBe("/overview");

    // The server is back, but its in-memory sessions are gone.
    backend.stub.mockImplementation(original!);
    backend.expire();
    await sleep(COOLDOWN + 50);
    act(() => source().emit("error", { closed: true }));

    expect(await screen.findByText(/Votre session a expiré/)).toBeInTheDocument();
    expect(view.router.state.location.pathname).toBe("/login");
  });

  it("collapses a burst of errors into one request plus at most one trailing check", async () => {
    const { backend, source } = await start();
    const before = meCalls(backend);
    act(() => {
      for (let i = 0; i < 10; i += 1) source().emit("error");
    });
    await waitFor(() => expect(meCalls(backend)).toBe(before + 1));
    expect(meCalls(backend)).toBe(before + 1);

    await sleep(COOLDOWN * 3);
    expect(meCalls(backend)).toBeLessThanOrEqual(before + 2);
  });

  it("does not lose the error suppressed by the cooldown: the trailing check finds the 401", async () => {
    const { backend, source } = await start();
    act(() => source().emit("error")); // immediate check: session fine
    await waitFor(() => expect(meCalls(backend)).toBe(2));

    backend.expire();
    act(() => source().emit("error", { closed: true })); // inside the cooldown
    expect(meCalls(backend)).toBe(2);

    expect(await screen.findByText(/Votre session a expiré/)).toBeInTheDocument();
    expect(meCalls(backend)).toBe(3);
  });

  it("treats session_ended as a reason to check", async () => {
    const { backend, source, view } = await start();
    backend.expire();
    act(() => source().emit("session_ended"));
    expect(await screen.findByText(/Votre session a expiré/)).toBeInTheDocument();
    expect(view.router.state.location.pathname).toBe("/login");
  });

  it("reopens a closed stream once when the session is still valid, never two live", async () => {
    const { events, backend, source } = await start();
    const first = source();
    act(() => {
      for (let i = 0; i < 5; i += 1) first.emit("error", { closed: true });
    });

    await waitFor(() => expect(events.instances).toHaveLength(2));
    expect(first.closed).toBe(true);
    expect(events.live).toBe(1);

    // The trailing check from the burst must not open a third source.
    await sleep(COOLDOWN * 3);
    expect(events.instances).toHaveLength(2);
    expect(events.live).toBe(1);
    expect(meCalls(backend)).toBeLessThanOrEqual(3);
  });

  it("does not reopen while the browser is still reconnecting on its own", async () => {
    const { events, source } = await start();
    act(() => source().emit("error"));
    await sleep(COOLDOWN);
    expect(events.instances).toHaveLength(1);
  });

  it("makes no requests after logout, even if the old stream errors", async () => {
    const { backend, source } = await start();
    const old = source();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Se déconnecter" }));
    await screen.findByRole("heading", { name: "Connexion à MCMA" });

    const before = backend.stub.mock.calls.length;
    act(() => {
      old.emit("error", { closed: true });
      old.emit("session_ended");
    });
    await sleep(COOLDOWN * 2);
    expect(backend.stub.mock.calls.length).toBe(before);
  });
});
