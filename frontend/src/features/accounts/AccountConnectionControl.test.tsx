import { describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderAppAt } from "../../test/renderApp";
import { mockRoutes, setCsrfCookie } from "../../test/apiMock";
import { connectionLabel, connectionMarker } from "@shared/utils/accountIdentity";
import {
  READ_ONLY_ACCOUNT_WIRE,
  TEST_ACCOUNTS_WIRE,
  WRITABLE_ACCOUNT_WIRE,
} from "../../test/fixtures";

const WRITABLE_ID = WRITABLE_ACCOUNT_WIRE.account_id;
const READ_ONLY_ID = READ_ONLY_ACCOUNT_WIRE.account_id;

interface Options {
  readonly accounts?: readonly unknown[];
  readonly loginStatus?: number;
  readonly refreshStatus?: number;
}

function backend(options: Options = {}) {
  return mockRoutes([
    {
      match: (url, init) => url.includes("/login") && init.method === "POST",
      status: options.loginStatus ?? 200,
      body:
        (options.loginStatus ?? 200) === 200
          ? { account_id: WRITABLE_ID, session_id: "session-1" }
          : {
              error: "PORTAL_LOGIN_FAILED_LoginTimedOut",
              message: "the portal login did not complete -- finish signing in",
              correlation_id: "0",
            },
    },
    {
      match: (url, init) => url.includes("/refresh-notifications") && init.method === "POST",
      status: options.refreshStatus ?? 200,
      body:
        (options.refreshStatus ?? 200) === 200
          ? { account_id: WRITABLE_ID, outcome: "POLLED", message: "Notifications actualisées." }
          : { error: "REFRESH_FAILED_TimeoutError", message: "l'actualisation a échoué", correlation_id: "0" },
    },
    { match: (url) => url.startsWith("/accounts"), body: { accounts: options.accounts ?? TEST_ACCOUNTS_WIRE } },
    { match: (url) => url.startsWith("/claims"), body: { claims: [] } },
    { match: (url) => url.startsWith("/jobs"), body: { jobs: [] } },
  ]);
}

function rail() {
  return screen.getByRole("navigation", { name: "Comptes portail" });
}

describe("the control matches the backend connection state", () => {
  it("offers Se connecter for an account that was never connected", async () => {
    backend({ accounts: [{ ...WRITABLE_ACCOUNT_WIRE, connection_state: "NOT_CONNECTED" }] });
    renderAppAt("/overview");
    expect(await screen.findByRole("button", { name: "Se connecter" })).toBeInTheDocument();
  });

  it("offers Reconnecter for an expired session", async () => {
    backend({ accounts: [{ ...WRITABLE_ACCOUNT_WIRE, connection_state: "RECONNECT_REQUIRED" }] });
    renderAppAt("/overview");
    expect(await screen.findByRole("button", { name: "Reconnecter" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Se connecter" })).toBeNull();
  });

  it("offers Actualiser for a connected account", async () => {
    backend({ accounts: [{ ...WRITABLE_ACCOUNT_WIRE, connection_state: "CONNECTED" }] });
    renderAppAt("/overview");
    expect(await screen.findByRole("button", { name: "Actualiser" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Se connecter" })).toBeNull();
  });

  it("gives a read-only account the control but still no agent entry", async () => {
    // Connecting a MAMDA profile is how its notifications are read. That is
    // unrelated to portal automation, which it still never gets.
    backend();
    const user = userEvent.setup();
    renderAppAt(`/accounts/${READ_ONLY_ID}/work`);

    // The rail loads after the screen heading, so wait for its control.
    await screen.findByRole("button", { name: "Reconnecter" });
    expect(rail()).toHaveTextContent("Reconnecter");
    await user.click(screen.getByRole("link", { name: /MAMDA • ZONE-B/ }));
    expect(screen.queryByRole("link", { name: "Agent dossier" })).toBeNull();
  });
});

describe("login", () => {
  it("posts to the account's own login route with no credentials", async () => {
    setCsrfCookie();
    const stub = backend({ accounts: [{ ...WRITABLE_ACCOUNT_WIRE, connection_state: "NOT_CONNECTED" }] });
    const user = userEvent.setup();
    renderAppAt("/overview");

    await user.click(await screen.findByRole("button", { name: "Se connecter" }));

    await waitFor(() => {
      const posted = stub.mock.calls.find(([url]) => (url as string).includes("/login"));
      expect(posted?.[0]).toBe(`/accounts/${WRITABLE_ID}/login`);
      const init = posted?.[1] as RequestInit;
      const body = JSON.parse(init.body as string) as Record<string, unknown>;
      expect(body).toEqual({});
      for (const field of ["username", "password", "otp", "account_id", "credentials"]) {
        expect(body).not.toHaveProperty(field);
      }
      expect(init.credentials).toBe("include");
      expect((init.headers as Record<string, string>)["X-CSRF-Token"]).toBeDefined();
    });
  });

  it("targets only the account whose button was pressed", async () => {
    setCsrfCookie();
    const stub = backend();
    const user = userEvent.setup();
    renderAppAt("/overview");

    await screen.findAllByRole("button", { name: /Se connecter|Reconnecter|Actualiser/ });
    await user.click(screen.getByRole("button", { name: "Reconnecter" }));

    await waitFor(() => {
      const logins = stub.mock.calls
        .map(([url]) => url as string)
        .filter((url) => url.includes("/login"));
      expect(logins).toEqual([`/accounts/${READ_ONLY_ID}/login`]);
    });
  });

  it("refetches the accounts rather than assuming it worked", async () => {
    setCsrfCookie();
    const stub = backend({ accounts: [{ ...WRITABLE_ACCOUNT_WIRE, connection_state: "NOT_CONNECTED" }] });
    const user = userEvent.setup();
    renderAppAt("/overview");

    const before = stub.mock.calls.filter(([url]) => (url as string).startsWith("/accounts")).length;
    await user.click(await screen.findByRole("button", { name: "Se connecter" }));

    await waitFor(() => {
      const after = stub.mock.calls.filter(
        ([url, init]) =>
          (url as string).startsWith("/accounts") &&
          (init as RequestInit | undefined)?.method !== "POST",
      ).length;
      expect(after).toBeGreaterThan(before);
    });
  });

  it("never invents a connected state", async () => {
    setCsrfCookie();
    // The backend still reports NOT_CONNECTED after the call, because the
    // employee has not finished signing in yet.
    backend({ accounts: [{ ...WRITABLE_ACCOUNT_WIRE, connection_state: "NOT_CONNECTED" }] });
    const user = userEvent.setup();
    renderAppAt("/overview");

    await user.click(await screen.findByRole("button", { name: "Se connecter" }));

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Se connecter" })).toBeEnabled(),
    );
    expect(screen.queryByRole("button", { name: "Actualiser" })).toBeNull();
    expect(rail()).toHaveTextContent("Jamais connecté".replace("Jamais", "Non"));
  });

  it("prevents a second click while the window is opening", async () => {
    setCsrfCookie();
    let resolve: (() => void) | undefined;
    const gate = new Promise<void>((r) => {
      resolve = r;
    });
    const stub = vi.fn((url: string, init: RequestInit = {}) => {
      if (url.includes("/login")) {
        return gate.then(
          () =>
            ({
              ok: true,
              status: 200,
              text: () => Promise.resolve(JSON.stringify({ account_id: WRITABLE_ID })),
            }) as unknown as Response,
        );
      }
      const body = url.startsWith("/accounts")
        ? { accounts: [{ ...WRITABLE_ACCOUNT_WIRE, connection_state: "NOT_CONNECTED" }] }
        : url.startsWith("/claims")
          ? { claims: [] }
          : { jobs: [] };
      void init;
      return Promise.resolve({
        ok: true,
        status: 200,
        text: () => Promise.resolve(JSON.stringify(body)),
      } as unknown as Response);
    });
    vi.stubGlobal("fetch", stub);

    const user = userEvent.setup();
    renderAppAt("/overview");

    const button = await screen.findByRole("button", { name: "Se connecter" });
    await user.click(button);

    await waitFor(() => expect(screen.getByRole("button", { name: "Connexion…" })).toBeDisabled());
    // A second portal window is exactly what must not happen.
    await user.click(screen.getByRole("button", { name: "Connexion…" }));
    expect(stub.mock.calls.filter(([url]) => (url as string).includes("/login"))).toHaveLength(1);

    resolve?.();
  });
});

describe("refresh", () => {
  const connected = [{ ...WRITABLE_ACCOUNT_WIRE, connection_state: "CONNECTED" }];

  it("posts to the account's own refresh route and shows the backend sentence", async () => {
    setCsrfCookie();
    const stub = backend({ accounts: connected });
    const user = userEvent.setup();
    renderAppAt("/overview");

    await user.click(await screen.findByRole("button", { name: "Actualiser" }));

    await waitFor(() => {
      const posted = stub.mock.calls.find(([url]) =>
        (url as string).includes("/refresh-notifications"),
      );
      expect(posted?.[0]).toBe(`/accounts/${WRITABLE_ID}/refresh-notifications`);
      expect(JSON.parse((posted?.[1] as RequestInit).body as string)).toEqual({});
    });
    expect(await screen.findByText("Notifications actualisées.")).toBeInTheDocument();
  });

  it("refetches the target account's claims and touches no other account's", async () => {
    setCsrfCookie();
    const stub = backend({
      accounts: [
        { ...WRITABLE_ACCOUNT_WIRE, connection_state: "CONNECTED" },
        READ_ONLY_ACCOUNT_WIRE,
      ],
    });
    const user = userEvent.setup();
    // The refreshed account's work queue is open, so its claims query is
    // active and an invalidation is observable as a real refetch.
    renderAppAt(`/accounts/${WRITABLE_ID}/work`);
    await screen.findByRole("button", { name: "Actualiser" });

    const targetBefore = stub.mock.calls.filter(([url]) =>
      (url as string).startsWith(`/claims?account_id=${WRITABLE_ID}`),
    ).length;

    await user.click(screen.getByRole("button", { name: "Actualiser" }));

    await waitFor(() => {
      const targetAfter = stub.mock.calls.filter(([url]) =>
        (url as string).startsWith(`/claims?account_id=${WRITABLE_ID}`),
      ).length;
      expect(targetAfter).toBeGreaterThan(targetBefore);
    });

    // The other account's rows were never requested, so nothing of its cache
    // was disturbed by a refresh that had nothing to do with it.
    expect(
      stub.mock.calls.some(([url]) =>
        (url as string).startsWith(`/claims?account_id=${READ_ONLY_ID}`),
      ),
    ).toBe(false);
  });
});

describe("errors", () => {
  it("shows a safe sentence and no raw backend text", async () => {
    setCsrfCookie();
    backend({
      accounts: [{ ...WRITABLE_ACCOUNT_WIRE, connection_state: "NOT_CONNECTED" }],
      loginStatus: 409,
    });
    const user = userEvent.setup();
    renderAppAt("/overview");

    await user.click(await screen.findByRole("button", { name: "Se connecter" }));

    const alert = await screen.findByRole("alert");
    expect(alert.textContent ?? "").not.toContain("finish signing in");
    expect(alert.textContent ?? "").not.toContain("LoginTimedOut");
    expect(alert.textContent ?? "").not.toContain(WRITABLE_ID);
    // The button comes back so the employee can try again.
    expect(screen.getByRole("button", { name: "Se connecter" })).toBeEnabled();
  });

  it("leaves the other accounts usable when one fails", async () => {
    setCsrfCookie();
    backend({ loginStatus: 409 });
    const user = userEvent.setup();
    renderAppAt("/overview");

    await screen.findAllByRole("button", { name: /Se connecter|Reconnecter|Actualiser/ });
    await user.click(screen.getByRole("button", { name: "Reconnecter" }));

    await screen.findByRole("alert");
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    for (const button of screen.getAllByRole("button")) {
      expect(button).toBeEnabled();
    }
  });
});

describe("the unverified state", () => {
  const unverified = [{ ...WRITABLE_ACCOUNT_WIRE, connection_state: "UNVERIFIED" }];

  it("says the session exists but is not confirmed", async () => {
    backend({ accounts: unverified });
    renderAppAt("/overview");

    expect(await screen.findByRole("button", { name: "Vérifier" })).toBeInTheDocument();
    expect(rail()).toHaveTextContent("Connexion à vérifier");
    // Not "expired": it has not been shown to be anything yet.
    expect(rail()).not.toHaveTextContent("Reconnexion requise");
    expect(screen.queryByRole("button", { name: "Se connecter" })).toBeNull();
  });

  it("checks with the stored session rather than demanding another OTP", async () => {
    setCsrfCookie();
    const stub = backend({ accounts: unverified });
    const user = userEvent.setup();
    renderAppAt("/overview");

    await user.click(await screen.findByRole("button", { name: "Vérifier" }));

    await waitFor(() => {
      const posted = stub.mock.calls.find(([url]) =>
        (url as string).includes("/refresh-notifications"),
      );
      expect(posted?.[0]).toBe(`/accounts/${WRITABLE_ID}/refresh-notifications`);
    });
    // No login window was opened for a session that may be perfectly good.
    expect(stub.mock.calls.some(([url]) => (url as string).includes("/login"))).toBe(false);
  });

  it("still offers reconnecting when checking cannot settle it", async () => {
    setCsrfCookie();
    const stub = backend({ accounts: unverified });
    const user = userEvent.setup();
    renderAppAt("/overview");

    await user.click(await screen.findByRole("button", { name: "Reconnecter" }));

    await waitFor(() => {
      const posted = stub.mock.calls.find(([url]) => (url as string).includes("/login"));
      expect(posted?.[0]).toBe(`/accounts/${WRITABLE_ID}/login`);
    });
  });
});

describe("each state maps to the action that actually helps", () => {
  it("connected refreshes", async () => {
    setCsrfCookie();
    const stub = backend({ accounts: [{ ...WRITABLE_ACCOUNT_WIRE, connection_state: "CONNECTED" }] });
    const user = userEvent.setup();
    renderAppAt("/overview");

    await user.click(await screen.findByRole("button", { name: "Actualiser" }));
    await waitFor(() =>
      expect(
        stub.mock.calls.some(([url]) => (url as string).includes("/refresh-notifications")),
      ).toBe(true),
    );
    expect(stub.mock.calls.some(([url]) => (url as string).includes("/login"))).toBe(false);
  });

  it("reconnect-required signs in again", async () => {
    setCsrfCookie();
    const stub = backend({
      accounts: [{ ...WRITABLE_ACCOUNT_WIRE, connection_state: "RECONNECT_REQUIRED" }],
    });
    const user = userEvent.setup();
    renderAppAt("/overview");

    await user.click(await screen.findByRole("button", { name: "Reconnecter" }));
    await waitFor(() =>
      expect(stub.mock.calls.some(([url]) => (url as string).includes("/login"))).toBe(true),
    );
  });

  it("never-connected signs in", async () => {
    setCsrfCookie();
    const stub = backend({
      accounts: [{ ...WRITABLE_ACCOUNT_WIRE, connection_state: "NOT_CONNECTED" }],
    });
    const user = userEvent.setup();
    renderAppAt("/overview");

    await user.click(await screen.findByRole("button", { name: "Se connecter" }));
    await waitFor(() =>
      expect(stub.mock.calls.some(([url]) => (url as string).includes("/login"))).toBe(true),
    );
  });

  it("gives every state its own label and marker", () => {
    // Colour is never the only signal: four labels, four marker shapes.
    const states = ["CONNECTED", "UNVERIFIED", "RECONNECT_REQUIRED", "NOT_CONNECTED"] as const;
    const labels = states.map(connectionLabel);
    const markers = states.map(connectionMarker);
    expect(new Set(labels).size).toBe(4);
    expect(new Set(markers).size).toBe(4);
    expect(connectionLabel("UNVERIFIED")).toBe("Connexion à vérifier");
  });
});
