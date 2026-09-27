import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { clearCookies, mockRoutes, setCsrfCookie } from "../../test/apiMock";
import {
  GOOD_PASSWORD,
  installEventSourceCounter,
  meWire,
  mockAuthBackend,
} from "../../test/authMock";
import { createTestQueryClient, renderAppAt } from "../../test/renderApp";
import { WRITABLE_ACCOUNT_WIRE } from "../../test/fixtures";

const PROBE = { auth: "probe" } as const;

async function signIn(user: ReturnType<typeof userEvent.setup>, password = GOOD_PASSWORD) {
  await user.type(await screen.findByLabelText("Nom d'utilisateur"), "admin");
  await user.type(screen.getByLabelText("Mot de passe"), password);
  await user.click(screen.getByRole("button", { name: "Se connecter" }));
}

describe("session gate", () => {
  it("shows an accessible loading state and starts nothing while /auth/me is pending", async () => {
    const events = installEventSourceCounter();
    const stub = mockRoutes([]);
    stub.mockImplementation(() => new Promise(() => {}));
    renderAppAt("/overview", undefined, PROBE);

    expect(screen.getByRole("status")).toHaveTextContent("Vérification de la session…");
    expect(stub.mock.calls.map(([url]) => url)).toEqual(["/auth/me"]);
    expect(events.opened).toBe(0);
  });

  it("redirects an unauthenticated visitor to /login without account queries or a stream", async () => {
    const events = installEventSourceCounter();
    const backend = mockAuthBackend({ signedIn: false });
    const view = renderAppAt("/overview", undefined, PROBE);

    expect(await screen.findByRole("heading", { name: "Connexion à MCMA" })).toBeInTheDocument();
    expect(view.router.state.location.pathname).toBe("/login");
    expect(backend.urls()).toEqual(["/auth/me"]);
    expect(events.opened).toBe(0);
  });

  it("starts the shell only after the session is confirmed", async () => {
    const events = installEventSourceCounter();
    const backend = mockAuthBackend({ signedIn: true });
    renderAppAt("/overview", undefined, PROBE);

    await screen.findByRole("heading", { name: "Vue d'ensemble" });
    expect(backend.urls()[0]).toBe("/auth/me");
    expect(backend.calls("/accounts")).toBeGreaterThan(0);
    expect(events.opened).toBe(1);
  });

  it("redirects an already authenticated visitor away from /login", async () => {
    mockAuthBackend({ signedIn: true });
    const view = renderAppAt("/login", undefined, PROBE);
    await screen.findByRole("heading", { name: "Vue d'ensemble" });
    expect(view.router.state.location.pathname).toBe("/overview");
  });

  it("offers a retry when the server cannot be reached", async () => {
    const stub = mockRoutes([]);
    stub.mockImplementation(() => Promise.reject(new TypeError("Failed")));
    renderAppAt("/overview", undefined, PROBE);
    expect(await screen.findByRole("button", { name: "Réessayer" })).toBeInTheDocument();
  });
});

describe("login", () => {
  it("logs in, sends no CSRF header, stores nothing in web storage, and lands on the overview", async () => {
    clearCookies();
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    const backend = mockAuthBackend({ signedIn: false });
    const user = userEvent.setup();
    const view = renderAppAt("/login", undefined, PROBE);

    await signIn(user);
    await screen.findByRole("heading", { name: "Vue d'ensemble" });
    expect(view.router.state.location.pathname).toBe("/overview");

    const loginCall = backend.stub.mock.calls.find(([url]) => url === "/auth/login");
    const init = loginCall?.[1] as RequestInit;
    expect((init.headers as Record<string, string>)["X-CSRF-Token"]).toBeUndefined();
    expect(init.credentials).toBe("include");
    expect(setItem).not.toHaveBeenCalled();
    expect(window.localStorage.length).toBe(0);
    expect(window.sessionStorage.length).toBe(0);
  });

  it("exposes labelled, autocomplete-hinted fields", async () => {
    mockAuthBackend({ signedIn: false });
    renderAppAt("/login", undefined, PROBE);
    const name = await screen.findByLabelText("Nom d'utilisateur");
    expect(name).toHaveAttribute("autocomplete", "username");
    const pw = screen.getByLabelText("Mot de passe");
    expect(pw).toHaveAttribute("type", "password");
    expect(pw).toHaveAttribute("autocomplete", "current-password");
  });

  it("shows one generic message on failure and clears the password", async () => {
    mockAuthBackend({ signedIn: false });
    const user = userEvent.setup();
    renderAppAt("/login", undefined, PROBE);

    await signIn(user, "wrong-password-value");
    expect(await screen.findByRole("alert")).toHaveTextContent("Identifiants incorrects.");
    expect(screen.getByLabelText("Mot de passe")).toHaveValue("");
    expect(screen.getByLabelText("Nom d'utilisateur")).toHaveValue("admin");
  });

  it("shows a network message when the server is unreachable", async () => {
    const backend = mockAuthBackend({ signedIn: false });
    const user = userEvent.setup();
    renderAppAt("/login", undefined, PROBE);
    await screen.findByLabelText("Nom d'utilisateur");
    backend.stub.mockImplementation(() => Promise.reject(new TypeError("Failed")));
    await signIn(user);
    expect(await screen.findByRole("alert")).toHaveTextContent(/injoignable/);
  });

  it("disables the submit button during the request", async () => {
    const backend = mockAuthBackend({ signedIn: false });
    const user = userEvent.setup();
    renderAppAt("/login", undefined, PROBE);
    await screen.findByLabelText("Nom d'utilisateur");
    backend.stub.mockImplementation(() => new Promise(() => {}));
    await signIn(user);
    expect(screen.getByRole("button", { name: "Se connecter" })).toBeDisabled();
  });
});

describe("intended route", () => {
  it("returns to the originally requested route after login", async () => {
    mockAuthBackend({ signedIn: false });
    const user = userEvent.setup();
    const path = `/accounts/${WRITABLE_ACCOUNT_WIRE.account_id}/work`;
    const view = renderAppAt(path, undefined, PROBE);

    await signIn(user);
    await screen.findByRole("heading", { name: "File de travail" });
    expect(view.router.state.location.pathname).toBe(path);
  });

  it.each(["//evil.example", "/\\evil.example", "https://evil.example", "/login", "evil"])(
    "ignores the unsafe intended route %s",
    async (unsafe) => {
      mockAuthBackend({ signedIn: false });
      const user = userEvent.setup();
      const view = renderAppAt("/login", undefined, PROBE);
      await screen.findByLabelText("Nom d'utilisateur");
      await act(async () => {
        await view.router.navigate("/login", { state: { from: unsafe } });
      });

      await signIn(user);
      await screen.findByRole("heading", { name: "Vue d'ensemble" });
      expect(view.router.state.location.pathname).toBe("/overview");
    },
  );
});

describe("header identity", () => {
  it("shows the username, the French role and the central-server label", async () => {
    mockAuthBackend({ signedIn: true, me: { username: "salma", role: "operator" } });
    renderAppAt("/overview", undefined, PROBE);
    expect(await screen.findByText("salma")).toBeInTheDocument();
    expect(screen.getByText("Opérateur")).toBeInTheDocument();
    expect(screen.getByText("Serveur central")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Se déconnecter" })).toBeInTheDocument();
  });

  it.each([
    ["viewer", "Lecteur"],
    ["admin", "Administrateur"],
  ])("labels the %s role", async (role, label) => {
    mockAuthBackend({ signedIn: true, me: { role } });
    renderAppAt("/overview", undefined, PROBE);
    expect(await screen.findByText(label)).toBeInTheDocument();
  });

  it("hides logout and says Poste local for the local single-user install", async () => {
    mockAuthBackend({ signedIn: true, me: { local_single_user: true } });
    renderAppAt("/overview", undefined, PROBE);
    expect(await screen.findByText("Poste local")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Se déconnecter" })).toBeNull();
    expect(screen.queryByText("Serveur central")).toBeNull();
  });
});

describe("logout", () => {
  it("logs out once with the CSRF header, clears the cache and returns to /login", async () => {
    setCsrfCookie("csrf-abc");
    const events = installEventSourceCounter();
    const backend = mockAuthBackend({ signedIn: true });
    const queryClient = createTestQueryClient();
    const clear = vi.spyOn(queryClient, "clear");
    const user = userEvent.setup();
    const view = renderAppAt("/overview", queryClient, PROBE);

    await screen.findByRole("heading", { name: "Vue d'ensemble" });
    await waitFor(() => expect(queryClient.getQueryCache().getAll().length).toBeGreaterThan(0));

    await user.dblClick(screen.getByRole("button", { name: "Se déconnecter" }));
    await screen.findByRole("heading", { name: "Connexion à MCMA" });

    const logouts = backend.stub.mock.calls.filter(([url]) => url === "/auth/logout");
    expect(logouts).toHaveLength(1);
    const headers = (logouts[0]?.[1] as RequestInit).headers as Record<string, string>;
    expect(headers["X-CSRF-Token"]).toBe("csrf-abc");
    expect(view.router.state.location.pathname).toBe("/login");
    expect(clear).toHaveBeenCalled();
    expect(queryClient.getQueryCache().getAll()).toHaveLength(0);
    expect(events.live).toBe(0);
    expect(screen.queryByText(/Votre session a expiré/)).toBeNull();

    // Nothing authenticated is requested after logout.
    const before = backend.stub.mock.calls.length;
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(backend.stub.mock.calls.length).toBe(before);
  });

  it("still signs out locally when the logout request fails", async () => {
    setCsrfCookie("csrf-abc");
    const backend = mockAuthBackend({ signedIn: true });
    const user = userEvent.setup();
    renderAppAt("/overview", undefined, PROBE);
    await screen.findByRole("heading", { name: "Vue d'ensemble" });
    const original = backend.stub.getMockImplementation();
    backend.stub.mockImplementation((url: string, init: RequestInit) =>
      url === "/auth/logout" ? Promise.reject(new TypeError("down")) : original?.(url, init),
    );
    await user.click(screen.getByRole("button", { name: "Se déconnecter" }));
    expect(await screen.findByRole("heading", { name: "Connexion à MCMA" })).toBeInTheDocument();
  });
});

describe("expired session", () => {
  it("handles a 401 from an authenticated call once, without retrying or logging out", async () => {
    const events = installEventSourceCounter();
    const backend = mockAuthBackend({ signedIn: true });
    const queryClient = createTestQueryClient();
    const clear = vi.spyOn(queryClient, "clear");
    const view = renderAppAt("/overview", queryClient, PROBE);
    await screen.findByRole("heading", { name: "Vue d'ensemble" });
    await waitFor(() => expect(backend.calls("/accounts")).toBeGreaterThan(0));

    backend.expire();
    clear.mockClear();
    const before = backend.calls("/");
    // A burst: several queries all fail with 401 at once.
    await act(async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["accounts"] }),
        queryClient.invalidateQueries({ queryKey: ["claims"] }),
        queryClient.invalidateQueries({ queryKey: ["jobs"] }),
      ]);
    });

    expect(await screen.findByRole("status")).toHaveTextContent(
      "Votre session a expiré. Veuillez vous reconnecter.",
    );
    expect(view.router.state.location.pathname).toBe("/login");
    expect(queryClient.getQueryCache().getAll()).toHaveLength(0);
    expect(clear).toHaveBeenCalledTimes(1);
    expect(events.live).toBe(0);
    expect(backend.calls("/auth/logout")).toBe(0);

    // No retry storm: nothing further is requested once signed out.
    const after = backend.calls("/");
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(backend.calls("/")).toBe(after);
    expect(after - before).toBeLessThanOrEqual(3);
  });

  it("recovers from a server restart: stream and queries then a 401 land on /login", async () => {
    const events = installEventSourceCounter();
    const backend = mockAuthBackend({ signedIn: true });
    const queryClient = createTestQueryClient();
    const user = userEvent.setup();
    const view = renderAppAt("/overview", queryClient, PROBE);
    await screen.findByRole("heading", { name: "Vue d'ensemble" });
    expect(events.live).toBe(1);

    backend.expire(); // in-memory sessions gone
    await act(async () => {
      await queryClient.invalidateQueries();
    });

    expect(await screen.findByText("Votre session a expiré. Veuillez vous reconnecter.")).toBeVisible();
    expect(view.router.state.location.pathname).toBe("/login");
    expect(events.live).toBe(0);

    // The login screen works again, and the intended route is restored.
    await signIn(user);
    await screen.findByRole("heading", { name: "Vue d'ensemble" });
    expect(screen.queryByText(/Votre session a expiré/)).toBeNull();
  });

  it("does not treat a failed login as an expired session", async () => {
    mockAuthBackend({ signedIn: false });
    const user = userEvent.setup();
    renderAppAt("/login", undefined, PROBE);
    await signIn(user, "wrong-password-value");
    await screen.findByRole("alert");
    expect(screen.queryByText(/Votre session a expiré/)).toBeNull();
  });
});

describe("meWire", () => {
  it("is a valid session body", () => {
    expect(meWire().role).toBe("admin");
  });
});
