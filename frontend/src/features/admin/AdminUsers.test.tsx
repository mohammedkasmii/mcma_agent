import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { mockRoutes, setCsrfCookie } from "../../test/apiMock";
import type { RouteHandler } from "../../test/apiMock";
import { TEST_ACCOUNTS_WIRE } from "../../test/fixtures";
import { renderAppAt, TEST_SESSION } from "../../test/renderApp";

const ZONE_A_ID = TEST_ACCOUNTS_WIRE[0]?.account_id as string;

const USERS = [
  { user_id: "u1", username: "admin", role: "admin", active: true, account_ids: [] },
  { user_id: "u2", username: "salma", role: "operator", active: true, account_ids: [ZONE_A_ID] },
];

interface Setup {
  readonly stub: ReturnType<typeof mockRoutes>;
  calls(method: string, prefix: string): [string, RequestInit][];
}

function backend(extra: readonly RouteHandler[] = [], users: unknown[] = USERS): Setup {
  setCsrfCookie("csrf-abc");
  const stub = mockRoutes([
    ...extra,
    { match: (url, init) => url === "/admin/users" && (init.method ?? "GET") === "GET", body: { users } },
    { match: (url) => url.startsWith("/accounts"), body: { accounts: TEST_ACCOUNTS_WIRE } },
    { match: (url) => url.startsWith("/claims"), body: { claims: [] } },
    { match: (url) => url.startsWith("/jobs"), body: { jobs: [] } },
  ]);
  return {
    stub,
    calls: (method, prefix) =>
      stub.mock.calls.filter(
        ([url, init]) =>
          (url as string).startsWith(prefix) && ((init as RequestInit)?.method ?? "GET") === method,
      ) as [string, RequestInit][],
  };
}

const err = (status: number, code: string): Partial<RouteHandler> => ({
  status,
  body: { error: code, message: "server text", correlation_id: "0" },
});

function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

describe("admin access", () => {
  it("shows the nav item and the page to an administrator", async () => {
    backend();
    renderAppAt("/administration/users");
    expect(
      await screen.findByRole("heading", { name: "Utilisateurs de la plateforme" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Utilisateurs" })).toBeInTheDocument();
    expect(screen.getByText(/ne concerne pas les identifiants du portail MCMA\/MAMDA/)).toBeInTheDocument();
    expect(screen.getByText(/gère les utilisateurs de la plateforme/)).toBeInTheDocument();
    expect(screen.getByText(/consulte les informations/)).toBeInTheDocument();
    expect(await screen.findByText("salma")).toBeInTheDocument();
    expect(screen.getByText("Opérateur", { selector: "span" })).toBeInTheDocument();
  });

  it.each(["operator", "viewer"] as const)(
    "blocks a %s: no nav item, access-denied screen, no admin request",
    async (role) => {
      const b = backend();
      renderAppAt("/administration/users", undefined, { auth: { ...TEST_SESSION, role } });
      expect(await screen.findByText("Accès réservé aux administrateurs.")).toBeInTheDocument();
      expect(screen.queryByRole("link", { name: "Utilisateurs" })).toBeNull();
      expect(screen.queryByRole("heading", { name: "Utilisateurs de la plateforme" })).toBeNull();
      expect(b.calls("GET", "/admin/users")).toHaveLength(0);
    },
  );
});

describe("create user", () => {
  async function open() {
    const b = backend([
      {
        match: (url, init) => url === "/admin/users" && init.method === "POST",
        status: 201,
        body: { user: { user_id: "u3", username: "nadia", role: "viewer", active: true, account_ids: [ZONE_A_ID] } },
      },
    ]);
    const user = userEvent.setup();
    renderAppAt("/administration/users");
    await screen.findByText("salma");
    return { b, user, form: screen.getByRole("form", { name: "Créer un utilisateur" }) };
  }

  async function fill(user: ReturnType<typeof userEvent.setup>, confirm: string) {
    await user.type(screen.getByLabelText("Nom d'utilisateur", { selector: "#new-user-name" }), "nadia");
    await user.type(screen.getByLabelText("Mot de passe", { selector: "#new-user-password" }), "a-long-password-1");
    await user.type(screen.getByLabelText("Confirmer le mot de passe", { selector: "#new-user-confirm" }), confirm);
    await user.selectOptions(screen.getByLabelText("Rôle"), "viewer");
    await user.click(screen.getByLabelText("Compte de test A"));
  }

  it("validates the confirmation client-side and sends nothing", async () => {
    const { b, user } = await open();
    await fill(user, "different-password-2");
    await user.click(screen.getByRole("button", { name: "Créer l'utilisateur" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Les mots de passe ne correspondent pas.");
    expect(b.calls("POST", "/admin/users")).toHaveLength(0);
    expect(screen.getByLabelText("Mot de passe", { selector: "#new-user-password" })).toHaveValue("");
  });

  it("creates the user with CSRF, clears the passwords and refreshes the list", async () => {
    const { b, user } = await open();
    await fill(user, "a-long-password-1");
    await user.click(screen.getByRole("button", { name: "Créer l'utilisateur" }));

    await screen.findByText(/Utilisateur « nadia » créé/);
    const [, init] = b.calls("POST", "/admin/users")[0] as [string, RequestInit];
    expect(JSON.parse(String(init.body))).toEqual({
      username: "nadia",
      password: "a-long-password-1",
      role: "viewer",
      account_ids: [ZONE_A_ID],
    });
    expect((init.headers as Record<string, string>)["X-CSRF-Token"]).toBe("csrf-abc");
    expect(screen.getByLabelText("Mot de passe", { selector: "#new-user-password" })).toHaveValue("");
    expect(screen.getByLabelText("Confirmer le mot de passe")).toHaveValue("");
    await waitFor(() => expect(b.calls("GET", "/admin/users").length).toBeGreaterThanOrEqual(2));
  });

  it("disables the submit button while the request is pending", async () => {
    const gate = deferred();
    const b = backend();
    const original = b.stub.getMockImplementation();
    b.stub.mockImplementation(async (url: string, init: RequestInit) => {
      if (url === "/admin/users" && init?.method === "POST") await gate.promise;
      return original?.(url, init);
    });
    const user = userEvent.setup();
    renderAppAt("/administration/users");
    await screen.findByText("salma");
    await fill(user, "a-long-password-1");
    await user.click(screen.getByRole("button", { name: "Créer l'utilisateur" }));
    expect(screen.getByRole("button", { name: "Créer l'utilisateur" })).toBeDisabled();
    gate.resolve();
    await waitFor(() => expect(screen.getByRole("button", { name: "Créer l'utilisateur" })).toBeEnabled());
  });

  it.each([
    [409, "USERNAME_TAKEN", "Ce nom d'utilisateur existe déjà."],
    [400, "PASSWORD_TOO_SHORT", "Le mot de passe doit contenir au moins 12 caractères."],
    [400, "USERNAME_INVALID", "Nom d'utilisateur invalide"],
    [400, "PASSWORD_TOO_SIMPLE", "trop simple"],
    [400, "ACCOUNT_UNKNOWN", "n'existe pas"],
  ])("maps %s %s to French and clears the password", async (status, code, text) => {
    const b = backend([{ match: (url, init) => url === "/admin/users" && init.method === "POST", ...err(status, code) } as RouteHandler]);
    const user = userEvent.setup();
    renderAppAt("/administration/users");
    await screen.findByText("salma");
    await fill(user, "a-long-password-1");
    await user.click(screen.getByRole("button", { name: "Créer l'utilisateur" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(text);
    expect(alert).not.toHaveTextContent("server text");
    expect(screen.getByLabelText("Mot de passe", { selector: "#new-user-password" })).toHaveValue("");
    expect(b.calls("POST", "/admin/users")).toHaveLength(1);
  });
});

describe("user actions", () => {
  it("deactivates a user with a PATCH and refreshes the list", async () => {
    const b = backend([
      {
        match: (url, init) => url === "/admin/users/u2" && init.method === "PATCH",
        body: { user: { ...USERS[1], active: false } },
      },
    ]);
    const user = userEvent.setup();
    renderAppAt("/administration/users");
    await screen.findByText("salma");
    await user.click(screen.getByRole("button", { name: "Désactiver salma" }));

    await waitFor(() => expect(b.calls("PATCH", "/admin/users/u2")).toHaveLength(1));
    const [, init] = b.calls("PATCH", "/admin/users/u2")[0] as [string, RequestInit];
    expect(JSON.parse(String(init.body))).toEqual({ active: false });
    expect((init.headers as Record<string, string>)["X-CSRF-Token"]).toBe("csrf-abc");
    await waitFor(() => expect(b.calls("GET", "/admin/users").length).toBeGreaterThanOrEqual(2));
  });

  it("offers reactivation for an inactive user", async () => {
    backend([], [{ ...USERS[1], active: false }]);
    renderAppAt("/administration/users");
    expect(await screen.findByRole("button", { name: "Réactiver salma" })).toBeInTheDocument();
    expect(screen.getByText("Désactivé")).toBeInTheDocument();
  });

  it.each([
    ["LAST_ADMIN", "au moins un administrateur actif"],
    ["SELF_LOCKOUT", "votre propre compte"],
  ])("shows the French message for %s", async (code, text) => {
    backend([{ match: (url, init) => url === "/admin/users/u2" && init.method === "PATCH", ...err(409, code) } as RouteHandler]);
    const user = userEvent.setup();
    renderAppAt("/administration/users");
    await screen.findByText("salma");
    await user.click(screen.getByRole("button", { name: "Désactiver salma" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(text);
  });

  async function openReset() {
    const b = backend([
      {
        match: (url, init) => url === "/admin/users/u2/password" && init.method === "POST",
        body: { status: "password_reset" },
      },
    ]);
    const user = userEvent.setup();
    renderAppAt("/administration/users");
    await screen.findByText("salma");
    await user.click(screen.getByRole("button", { name: "Réinitialiser le mot de passe de salma" }));
    const form = screen.getByRole("form", { name: "Réinitialiser le mot de passe de salma" });
    return { b, user, form };
  }

  it("validates the confirmation for a password reset", async () => {
    const { b, user, form } = await openReset();
    await user.type(within(form).getByLabelText(/^Nouveau mot de passe/), "a-long-password-1");
    await user.type(within(form).getByLabelText(/^Confirmer/), "other-password-22");
    await user.click(within(form).getByRole("button", { name: "Enregistrer le mot de passe" }));

    expect(await within(form).findByRole("alert")).toHaveTextContent("Les mots de passe ne correspondent pas.");
    expect(b.calls("POST", "/admin/users/u2/password")).toHaveLength(0);
    expect(within(form).getByLabelText(/^Nouveau mot de passe/)).toHaveValue("");
  });

  it("resets a password with CSRF and never redisplays it", async () => {
    const { b, user, form } = await openReset();
    await user.type(within(form).getByLabelText(/^Nouveau mot de passe/), "a-long-password-1");
    await user.type(within(form).getByLabelText(/^Confirmer/), "a-long-password-1");
    await user.click(within(form).getByRole("button", { name: "Enregistrer le mot de passe" }));

    await within(form).findByText("Mot de passe réinitialisé.");
    const [, init] = b.calls("POST", "/admin/users/u2/password")[0] as [string, RequestInit];
    expect(JSON.parse(String(init.body))).toEqual({ password: "a-long-password-1" });
    expect((init.headers as Record<string, string>)["X-CSRF-Token"]).toBe("csrf-abc");
    expect(within(form).getByLabelText(/^Nouveau mot de passe/)).toHaveValue("");
    expect(within(form).getByLabelText(/^Confirmer/)).toHaveValue("");
    expect(document.body).not.toHaveTextContent("a-long-password-1");
  });

  it("maps a server rejection of the new password and clears the fields", async () => {
    backend([
      {
        match: (url, init) => url === "/admin/users/u2/password" && init.method === "POST",
        ...err(400, "PASSWORD_CONTAINS_USERNAME"),
      } as RouteHandler,
    ]);
    const user = userEvent.setup();
    renderAppAt("/administration/users");
    await screen.findByText("salma");
    await user.click(screen.getByRole("button", { name: "Réinitialiser le mot de passe de salma" }));
    const form = screen.getByRole("form", { name: "Réinitialiser le mot de passe de salma" });
    await user.type(within(form).getByLabelText(/^Nouveau mot de passe/), "salma-password-1");
    await user.type(within(form).getByLabelText(/^Confirmer/), "salma-password-1");
    await user.click(within(form).getByRole("button", { name: "Enregistrer le mot de passe" }));

    expect(await within(form).findByRole("alert")).toHaveTextContent("ne doit pas contenir le nom d'utilisateur");
    expect(within(form).getByLabelText(/^Nouveau mot de passe/)).toHaveValue("");
  });
});

describe("page route versus API path", () => {
  it("serves the page from a URL distinct from the API and keeps data calls on /admin/users", async () => {
    const { ROUTES } = await import("@shared/utils/routes");
    expect(ROUTES.adminUsers).toBe("/administration/users");
    expect(ROUTES.adminUsers).not.toBe("/admin/users");

    const b = backend([
      { match: (url, init) => url === "/admin/users/u2" && init.method === "PATCH", body: { user: USERS[1] } },
      { match: (url, init) => url === "/admin/users/u2/password" && init.method === "POST", body: { status: "password_reset" } },
    ]);
    const user = userEvent.setup();
    renderAppAt(ROUTES.adminUsers);
    await screen.findByText("salma");
    expect(b.calls("GET", "/admin/users").length).toBeGreaterThan(0);

    await user.click(screen.getByRole("button", { name: "Désactiver salma" }));
    await waitFor(() => expect(b.calls("PATCH", "/admin/users/u2")).toHaveLength(1));

    await user.click(screen.getByRole("button", { name: "Réinitialiser le mot de passe de salma" }));
    const form = screen.getByRole("form", { name: "Réinitialiser le mot de passe de salma" });
    await user.type(within(form).getByLabelText(/^Nouveau mot de passe/), "a-long-password-1");
    await user.type(within(form).getByLabelText(/^Confirmer/), "a-long-password-1");
    await user.click(within(form).getByRole("button", { name: "Enregistrer le mot de passe" }));
    await waitFor(() => expect(b.calls("POST", "/admin/users/u2/password")).toHaveLength(1));
  });
});
