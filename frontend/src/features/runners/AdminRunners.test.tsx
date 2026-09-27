import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockRoutes, setCsrfCookie } from "../../test/apiMock";
import type { RouteHandler } from "../../test/apiMock";
import { TEST_ACCOUNTS_WIRE } from "../../test/fixtures";
import { createTestQueryClient, renderAppAt, TEST_SESSION } from "../../test/renderApp";
import { ROUTES } from "@shared/utils/routes";
import { ADMIN_RUNNERS_PATH } from "@shared/api/runners";

const CODE = "PAIR-SECRET-CODE-4711";

const RUNNERS = [
  {
    runner_id: "r1",
    user_id: "u1",
    username: "salma",
    runner_label: "Poste Oujda",
    status: "ONLINE",
    last_seen_at: "2026-02-01T10:00:00Z",
    created_at: "2026-01-01T10:00:00Z",
    revoked_at: null,
    app_version: "1.0.0",
    protocol_version: 1,
    sessions: [
      { account_id: "acct-mcma-oujda", state: "READY" },
      { account_id: "acct-mcma-nador", state: "LOGIN_REQUIRED" },
    ],
  },
  {
    runner_id: "r2",
    user_id: "u2",
    username: "karim",
    runner_label: null,
    status: "OFFLINE",
    last_seen_at: null,
    created_at: "2026-01-01T10:00:00Z",
    revoked_at: null,
    app_version: null,
    protocol_version: null,
    sessions: [{ account_id: "acct-mcma-oujda", state: "ERROR" }],
  },
  {
    runner_id: "r3",
    user_id: "u3",
    username: "nadia",
    runner_label: "Ancien",
    status: "REVOKED",
    last_seen_at: null,
    created_at: "2026-01-01T10:00:00Z",
    revoked_at: "2026-01-15T10:00:00Z",
    app_version: null,
    protocol_version: null,
    sessions: [],
  },
];

const OVERVIEW = {
  runners: RUNNERS,
  pending_enrollments: [
    {
      enrollment_id: "e1",
      target_user_id: "u9",
      target_username: "youssef",
      runner_label: "Bureau",
      expires_at: "2026-02-01T10:10:00Z",
    },
  ],
  eligible_employees: [
    { user_id: "u4", username: "amine" },
    { user_id: "u5", username: "leila" },
  ],
  server_time: "2026-02-01T10:00:00Z",
  heartbeat_interval_seconds: 10,
  offline_after_seconds: 30,
};

function backend(extra: readonly RouteHandler[] = []) {
  setCsrfCookie("csrf-abc");
  const stub = mockRoutes([
    ...extra,
    { match: (url, init) => url === ADMIN_RUNNERS_PATH && (init.method ?? "GET") === "GET", body: OVERVIEW },
    { match: (url) => url.startsWith("/accounts"), body: { accounts: TEST_ACCOUNTS_WIRE } },
    { match: (url) => url.startsWith("/claims"), body: { claims: [] } },
    { match: (url) => url.startsWith("/jobs"), body: { jobs: [] } },
  ]);
  const calls = (method: string, prefix: string) =>
    stub.mock.calls.filter(
      ([url, init]) =>
        (url as string).startsWith(prefix) && ((init as RequestInit)?.method ?? "GET") === method,
    ) as [string, RequestInit][];
  return { stub, calls };
}

const enrollmentOk: RouteHandler = {
  match: (url, init) => url === "/admin/runner-enrollments" && init.method === "POST",
  status: 201,
  body: {
    enrollment: {
      enrollment_id: "e2",
      target_user_id: "u4",
      target_username: "amine",
      runner_label: null,
      expires_at: "2026-02-01T10:10:00Z",
    },
    pairing_code: CODE,
  },
};

const errBody = (code: string) => ({ error: code, message: "server text", correlation_id: "0" });

afterEach(() => {
  vi.useRealTimers();
});

describe("route and access", () => {
  it("uses a SPA URL distinct from the API path", () => {
    expect(ROUTES.adminRunners).toBe("/administration/runners");
    expect(ROUTES.adminRunners).not.toBe(ADMIN_RUNNERS_PATH);
  });

  it("shows the nav item and title to an administrator", async () => {
    backend();
    renderAppAt(ROUTES.adminRunners);
    expect(await screen.findByRole("heading", { name: "Postes agents" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Postes agents" })).toBeInTheDocument();
  });

  it.each(["operator", "viewer"] as const)(
    "blocks a %s with no nav item and no /admin/runners request",
    async (role) => {
      const b = backend();
      renderAppAt(ROUTES.adminRunners, undefined, { auth: { ...TEST_SESSION, role } });
      expect(await screen.findByText("Accès réservé aux administrateurs.")).toBeInTheDocument();
      expect(screen.queryByRole("link", { name: "Postes agents" })).toBeNull();
      expect(b.calls("GET", "/admin/runners")).toHaveLength(0);
    },
  );
});

describe("runner list", () => {
  it("renders statuses, readiness labels, last seen and pending enrollments", async () => {
    backend();
    renderAppAt(ROUTES.adminRunners);
    await screen.findByText("salma");
    const list = screen.getByRole("list", { name: "Liste des postes agents" });

    expect(within(list).getByText("En ligne")).toBeInTheDocument();
    expect(within(list).getByText("Hors ligne")).toBeInTheDocument();
    expect(within(list).getByText("Révoqué")).toBeInTheDocument();
    const salma = within(list).getByRole("list", { name: "Sessions de salma" });
    expect(salma).toHaveTextContent("MCMA Oujda : Prêt");
    expect(salma).toHaveTextContent("MCMA Nador : Connexion requise");
    // A missing session is NOT_CONFIGURED; an ERROR is shown as such.
    const karim = within(list).getByRole("list", { name: "Sessions de karim" });
    expect(karim).toHaveTextContent("MCMA Oujda : Erreur");
    expect(karim).toHaveTextContent("MCMA Nador : Non configuré");
    expect(within(list).getByText("Dernière activité : jamais")).toBeInTheDocument();
    // Revoked runners offer no sessions and no revoke button.
    expect(within(list).queryByRole("list", { name: "Sessions de nadia" })).toBeNull();
    expect(within(list).queryByRole("button", { name: /Révoquer le poste de nadia/ })).toBeNull();

    const pending = screen.getByRole("list", { name: "Associations en attente" });
    expect(pending).toHaveTextContent("youssef");
    expect(pending).toHaveTextContent("Bureau");
  });
});

describe("pairing code", () => {
  async function generate() {
    const b = backend([enrollmentOk]);
    const user = userEvent.setup();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
    const queryClient = createTestQueryClient();
    const view = renderAppAt(ROUTES.adminRunners, queryClient);
    await screen.findByText("salma");
    await user.selectOptions(screen.getByLabelText("Employé"), "u4");
    await user.click(screen.getByRole("button", { name: "Générer un code d'association" }));
    return { b, user, writeText, queryClient, view };
  }

  it("shows the code once with the warning, copies it, and sends CSRF", async () => {
    const { b, user, writeText } = await generate();
    const box = await screen.findByRole("group", { name: "Code d'association" });
    expect(within(box).getByTestId("pairing-code")).toHaveTextContent(CODE);
    expect(box).toHaveTextContent(
      "Ce code n'est affiché qu'une seule fois et expire dans 10 minutes.",
    );

    const [, init] = b.calls("POST", "/admin/runner-enrollments")[0] as [string, RequestInit];
    expect(JSON.parse(String(init.body))).toEqual({ target_user_id: "u4" });
    expect((init.headers as Record<string, string>)["X-CSRF-Token"]).toBe("csrf-abc");

    await user.click(within(box).getByRole("button", { name: "Copier" }));
    expect(writeText).toHaveBeenCalledWith(CODE);
    expect(await within(box).findByText("Code copié.")).toBeInTheDocument();
  });

  it("falls back gracefully when the clipboard is unavailable", async () => {
    const { user, writeText } = await generate();
    writeText.mockRejectedValue(new Error("denied"));
    await user.click(await screen.findByRole("button", { name: "Copier" }));
    expect(await screen.findByText(/Copie impossible/)).toBeInTheDocument();
  });

  it("sends the optional label when given", async () => {
    const b = backend([enrollmentOk]);
    const user = userEvent.setup();
    renderAppAt(ROUTES.adminRunners);
    await screen.findByText("salma");
    await user.selectOptions(screen.getByLabelText("Employé"), "u5");
    await user.type(screen.getByLabelText(/Libellé du poste/), "Poste Nador");
    await user.click(screen.getByRole("button", { name: "Générer un code d'association" }));
    await screen.findByTestId("pairing-code");
    const [, init] = b.calls("POST", "/admin/runner-enrollments")[0] as [string, RequestInit];
    expect(JSON.parse(String(init.body))).toEqual({ target_user_id: "u5", runner_label: "Poste Nador" });
  });

  it("disappears when dismissed", async () => {
    const { user } = await generate();
    await screen.findByTestId("pairing-code");
    await user.click(screen.getByRole("button", { name: "Masquer le code" }));
    expect(screen.queryByTestId("pairing-code")).toBeNull();
    expect(document.body).not.toHaveTextContent(CODE);
  });

  it("is gone after unmount and never shown again on remount", async () => {
    const { view, queryClient } = await generate();
    await screen.findByTestId("pairing-code");
    view.unmount();
    renderAppAt(ROUTES.adminRunners, queryClient);
    await screen.findByText("salma");
    expect(document.body).not.toHaveTextContent(CODE);
  });

  it("is never kept in storage, cookies or the query and mutation caches", async () => {
    const { queryClient } = await generate();
    await screen.findByTestId("pairing-code");

    expect(window.localStorage.length).toBe(0);
    expect(window.sessionStorage.length).toBe(0);
    expect(document.cookie).not.toContain(CODE);
    expect(window.location.href).not.toContain(CODE);
    expect(Object.keys(window)).not.toContain("pairingCode");

    const queries = queryClient.getQueryCache().getAll().map((q) => q.state);
    const mutations = queryClient.getMutationCache().getAll().map((m) => m.state);
    expect(JSON.stringify(queries)).not.toContain(CODE);
    expect(JSON.stringify(mutations)).not.toContain(CODE);
  });

  it("disables the submit button while the request is pending", async () => {
    let release!: () => void;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const b = backend([enrollmentOk]);
    const original = b.stub.getMockImplementation();
    b.stub.mockImplementation(async (url: string, init: RequestInit) => {
      if (url === "/admin/runner-enrollments") await gate;
      return original?.(url, init);
    });
    const user = userEvent.setup();
    renderAppAt(ROUTES.adminRunners);
    await screen.findByText("salma");
    await user.selectOptions(screen.getByLabelText("Employé"), "u4");
    await user.click(screen.getByRole("button", { name: "Générer un code d'association" }));
    expect(screen.getByRole("button", { name: "Générer un code d'association" })).toBeDisabled();
    release();
    await screen.findByTestId("pairing-code");
  });

  it.each([
    ["TARGET_NOT_ELIGIBLE", 409, "ne peut pas recevoir de poste agent"],
    ["RUNNER_ALREADY_ACTIVE", 409, "a déjà un poste agent actif"],
    ["RUNNER_LABEL_INVALID", 400, "Libellé invalide"],
  ])("maps %s to French and shows no code", async (code, status, text) => {
    backend([
      {
        match: (url, init) => url === "/admin/runner-enrollments" && init.method === "POST",
        status,
        body: errBody(code),
      },
    ]);
    const user = userEvent.setup();
    renderAppAt(ROUTES.adminRunners);
    await screen.findByText("salma");
    await user.selectOptions(screen.getByLabelText("Employé"), "u4");
    await user.click(screen.getByRole("button", { name: "Générer un code d'association" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(text);
    expect(alert).not.toHaveTextContent("server text");
    expect(screen.queryByTestId("pairing-code")).toBeNull();
  });
});

describe("revoke", () => {
  const revokeOk: RouteHandler = {
    match: (url, init) => url === "/admin/runners/r1/revoke" && init.method === "POST",
    body: { runner: { ...RUNNERS[0], status: "REVOKED" }, already_revoked: false },
  };

  it("sends nothing until confirmed, and nothing when cancelled", async () => {
    const b = backend([revokeOk]);
    const user = userEvent.setup();
    renderAppAt(ROUTES.adminRunners);
    await screen.findByText("salma");

    await user.click(screen.getByRole("button", { name: /Révoquer le poste de salma/ }));
    expect(b.calls("POST", "/admin/runners")).toHaveLength(0);
    await user.click(screen.getByRole("button", { name: "Annuler" }));
    expect(b.calls("POST", "/admin/runners")).toHaveLength(0);
    expect(screen.queryByRole("button", { name: "Confirmer la révocation" })).toBeNull();
  });

  it("posts the revoke with CSRF after confirmation, then refetches", async () => {
    const b = backend([revokeOk]);
    const user = userEvent.setup();
    renderAppAt(ROUTES.adminRunners);
    await screen.findByText("salma");
    const before = b.calls("GET", "/admin/runners").length;

    await user.click(screen.getByRole("button", { name: /Révoquer le poste de salma/ }));
    await user.click(screen.getByRole("button", { name: "Confirmer la révocation" }));

    await waitFor(() => expect(b.calls("POST", "/admin/runners/r1/revoke")).toHaveLength(1));
    const [, init] = b.calls("POST", "/admin/runners/r1/revoke")[0] as [string, RequestInit];
    expect((init.headers as Record<string, string>)["X-CSRF-Token"]).toBe("csrf-abc");
    expect(init.body).toBeUndefined();
    await waitFor(() => expect(b.calls("GET", "/admin/runners").length).toBeGreaterThan(before));
  });

  it("maps RUNNER_NOT_FOUND to French", async () => {
    backend([
      {
        match: (url, init) => url === "/admin/runners/r1/revoke" && init.method === "POST",
        status: 404,
        body: errBody("RUNNER_NOT_FOUND"),
      },
    ]);
    const user = userEvent.setup();
    renderAppAt(ROUTES.adminRunners);
    await screen.findByText("salma");
    await user.click(screen.getByRole("button", { name: /Révoquer le poste de salma/ }));
    await user.click(screen.getByRole("button", { name: "Confirmer la révocation" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Ce poste agent est introuvable.");
  });
});

describe("polling", () => {
  it("polls only /admin/runners every 10 seconds and stops on unmount", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const b = backend();
    const view = renderAppAt(ROUTES.adminRunners);
    await screen.findByText("salma");

    const others = () =>
      b.stub.mock.calls
        .map(([url]) => url as string)
        .filter((url) => !url.startsWith("/admin/runners"));
    const runnerCalls = () => b.calls("GET", "/admin/runners").length;
    const otherBefore = others();
    const before = runnerCalls();

    await vi.advanceTimersByTimeAsync(10_500);
    expect(runnerCalls()).toBe(before + 1);
    await vi.advanceTimersByTimeAsync(10_000);
    expect(runnerCalls()).toBe(before + 2);
    // No polling was added for accounts, claims or jobs.
    expect(others()).toEqual(otherBefore);

    view.unmount();
    const after = runnerCalls();
    await vi.advanceTimersByTimeAsync(60_000);
    expect(runnerCalls()).toBe(after);
  });
});
