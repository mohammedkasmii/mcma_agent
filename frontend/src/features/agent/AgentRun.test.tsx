import { describe, expect, it, vi } from "vitest";
import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderAppAt } from "../../test/renderApp";
import { mockRoutes, setCsrfCookie } from "../../test/apiMock";
import {
  DRY_RUN_JOB_WIRE,
  EXECUTION_JOB_WIRE,
  PLAN_NEEDS_REVIEW_WIRE,
  PLAN_WIRE,
  READ_ONLY_ACCOUNT_WIRE,
  SYNTHETIC_DOSSIER,
  TEST_ACCOUNTS_WIRE,
  WRITABLE_ACCOUNT_WIRE,
} from "../../test/fixtures";

const WRITABLE_ID = WRITABLE_ACCOUNT_WIRE.account_id;
const READ_ONLY_ID = READ_ONLY_ACCOUNT_WIRE.account_id;
const agentPath = (accountId: string) => `/accounts/${accountId}/agent`;
const runPath = (accountId: string, jobId: string) =>
  `/accounts/${accountId}/agent/runs/${jobId}`;

interface BackendOptions {
  readonly job?: unknown;
  readonly plan?: unknown;
  readonly dryRunStatus?: number;
  readonly executionStatus?: number;
}

function backend(options: BackendOptions = {}) {
  return mockRoutes([
    { match: (url) => url.startsWith("/accounts"), body: { accounts: TEST_ACCOUNTS_WIRE } },
    {
      match: (url, init) => url === "/jobs/dry-runs" && init.method === "POST",
      status: options.dryRunStatus ?? 200,
      body:
        (options.dryRunStatus ?? 200) === 200
          ? { job_id: DRY_RUN_JOB_WIRE.job_id, status: "QUEUED" }
          : {
              error: "INVALID_TYPED_INPUT",
              message: "typed_input does not match the expected dossier shape",
              correlation_id: "0",
            },
    },
    {
      match: (url, init) => url.includes("/executions") && init.method === "POST",
      status: options.executionStatus ?? 200,
      body:
        (options.executionStatus ?? 200) === 200
          ? { job_id: EXECUTION_JOB_WIRE.job_id, status: "QUEUED" }
          : {
              error: "PARENT_NOT_DRY_RUN_VERIFIED",
              message: "the referenced job is not an approved dry-run",
              correlation_id: "0",
            },
    },
    { match: (url) => url.includes("/plan"), body: options.plan ?? PLAN_WIRE },
    {
      match: (url) => url.startsWith("/jobs"),
      body: { jobs: options.job === undefined ? [DRY_RUN_JOB_WIRE] : [options.job] },
    },
  ]);
}

/** A file whose text() resolves to the given string, for the upload input. */
function jsonFile(contents: string, name = "dossier-test.json"): File {
  const file = new File([contents], name, { type: "application/json" });
  Object.defineProperty(file, "text", { value: () => Promise.resolve(contents) });
  return file;
}

describe("new run", () => {
  it("is reachable only for a writable account", async () => {
    backend();
    renderAppAt(agentPath(READ_ONLY_ID));
    expect(await screen.findByText("Ce compte est en lecture seule")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Nouveau run" })).toBeNull();
  });

  it("refuses a directly typed run URL on a read-only account", async () => {
    backend();
    renderAppAt(runPath(READ_ONLY_ID, DRY_RUN_JOB_WIRE.job_id));
    expect(await screen.findByText("Ce compte est en lecture seule")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Autoriser/ })).toBeNull();
  });

  it("states what the agent will never do", async () => {
    backend();
    renderAppAt(agentPath(WRITABLE_ID));
    await screen.findByRole("heading", { name: "Nouveau run" });
    expect(screen.getByText(/Clôturer le dossier/)).toBeInTheDocument();
    expect(screen.getByText(/GED/)).toBeInTheDocument();
    expect(
      screen.getByText(/Aucune validation finale ni clôture n'est effectuée automatiquement/),
    ).toBeInTheDocument();
  });

  it("rejects a file that is not JSON without calling the API", async () => {
    setCsrfCookie();
    const stub = backend();
    const user = userEvent.setup();
    renderAppAt(agentPath(WRITABLE_ID));

    await screen.findByRole("heading", { name: "Nouveau run" });
    await user.upload(screen.getByLabelText("Fichier JSON"), jsonFile("{ pas du json"));

    expect(await screen.findByText("Ce fichier n'est pas un JSON valide.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Préparer le plan" })).toBeDisabled();
    // The shell reads GET /jobs for the active-run banner, so the assertion
    // is about the dry-run endpoint specifically.
    expect(stub.mock.calls.some(([url]) => (url as string) === "/jobs/dry-runs")).toBe(false);
  });

  it("sends the parsed dossier as a dry run and routes to the run", async () => {
    setCsrfCookie();
    const stub = backend();
    const user = userEvent.setup();
    renderAppAt(agentPath(WRITABLE_ID));

    await screen.findByRole("heading", { name: "Nouveau run" });
    await user.upload(
      screen.getByLabelText("Fichier JSON"),
      jsonFile(JSON.stringify(SYNTHETIC_DOSSIER)),
    );
    await screen.findByText(/Fichier prêt/);
    await user.click(screen.getByRole("button", { name: "Préparer le plan" }));

    await waitFor(() => {
      const posted = stub.mock.calls.find(([url]) => url === "/jobs/dry-runs");
      expect(posted).toBeDefined();
      const body = JSON.parse((posted?.[1] as RequestInit).body as string) as Record<
        string,
        unknown
      >;
      expect(body["account_id"]).toBe(WRITABLE_ID);
      expect(body["typed_input"]).toEqual(SYNTHETIC_DOSSIER);
      expect(typeof body["idempotency_key"]).toBe("string");
      expect(body).not.toHaveProperty("workflow_name");
      expect(body).not.toHaveProperty("mode");
    });

    // The run now has its own address, so a reload returns to it.
    expect(await screen.findByText(/Aucune écriture n’a été effectuée sur SinAuto\./)).toBeInTheDocument();
  });

  it("never renders the dossier contents, even after a backend refusal", async () => {
    setCsrfCookie();
    backend({ dryRunStatus: 400 });
    const user = userEvent.setup();
    const secret = { assure: "NE-DOIT-PAS-APPARAITRE", matricule: "XX-000-XX" };
    renderAppAt(agentPath(WRITABLE_ID));

    await screen.findByRole("heading", { name: "Nouveau run" });
    await user.upload(screen.getByLabelText("Fichier JSON"), jsonFile(JSON.stringify(secret)));
    await user.click(screen.getByRole("button", { name: "Préparer le plan" }));

    await screen.findByText("La préparation n'a pas pu démarrer");
    expect(document.body.textContent).not.toContain("NE-DOIT-PAS-APPARAITRE");
    expect(document.body.textContent).not.toContain("XX-000-XX");
    expect(document.body.textContent).not.toContain("typed_input");
  });

  it("stores nothing about the dossier in browser storage", async () => {
    setCsrfCookie();
    const user = userEvent.setup();
    backend();
    renderAppAt(agentPath(WRITABLE_ID));

    await screen.findByRole("heading", { name: "Nouveau run" });
    await user.upload(
      screen.getByLabelText("Fichier JSON"),
      jsonFile(JSON.stringify(SYNTHETIC_DOSSIER)),
    );

    expect(window.localStorage.length).toBe(0);
    expect(window.sessionStorage.length).toBe(0);
  });
});

describe("dry-run lifecycle", () => {
  it("does not poll a moving job — freshness comes from the event stream", async () => {
    vi.useFakeTimers();
    try {
      const stub = backend({ job: { ...DRY_RUN_JOB_WIRE, status: "PLANNING" } });
      renderAppAt(runPath(WRITABLE_ID, DRY_RUN_JOB_WIRE.job_id));

      await act(async () => void (await vi.advanceTimersByTimeAsync(50)));
      const first = stub.mock.calls.filter(([url]) =>
        (url as string).startsWith("/jobs?"),
      ).length;
      await act(async () => void (await vi.advanceTimersByTimeAsync(30000)));
      const later = stub.mock.calls.filter(([url]) =>
        (url as string).startsWith("/jobs?"),
      ).length;
      // No timer-driven refetch: SSE invalidation is the only refresh.
      expect(later).toBe(first);
    } finally {
      vi.useRealTimers();
    }
  });

  it("still loads the job from GET without waiting for any event", async () => {
    vi.useFakeTimers();
    try {
      const stub = backend({ job: DRY_RUN_JOB_WIRE });
      renderAppAt(runPath(WRITABLE_ID, DRY_RUN_JOB_WIRE.job_id));

      await act(async () => void (await vi.advanceTimersByTimeAsync(100)));
      const settled = stub.mock.calls.filter(([url]) =>
        (url as string).startsWith("/jobs?"),
      ).length;
      await act(async () => void (await vi.advanceTimersByTimeAsync(10000)));
      const after = stub.mock.calls.filter(([url]) =>
        (url as string).startsWith("/jobs?"),
      ).length;
      expect(after).toBe(settled);
    } finally {
      vi.useRealTimers();
    }
  });

  it("states that a verified dry run wrote nothing", async () => {
    backend({ job: DRY_RUN_JOB_WIRE });
    renderAppAt(runPath(WRITABLE_ID, DRY_RUN_JOB_WIRE.job_id));

    expect(
      await screen.findByText("Aucune écriture n’a été effectuée sur SinAuto."),
    ).toBeInTheDocument();
    // Never a claim that the portal was left untouched.
    expect(document.body.textContent).not.toContain("n'a pas été consulté");
  });

  it("fails closed for a run belonging to another account", async () => {
    backend({ job: { ...DRY_RUN_JOB_WIRE, account_id: READ_ONLY_ID } });
    renderAppAt(runPath(WRITABLE_ID, DRY_RUN_JOB_WIRE.job_id));
    expect(await screen.findByText("Impossible de charger ce run")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Autoriser/ })).toBeNull();
  });

  it("fails closed for a run the backend does not return", async () => {
    mockRoutes([
      { match: (url) => url.startsWith("/accounts"), body: { accounts: TEST_ACCOUNTS_WIRE } },
      { match: (url) => url.startsWith("/jobs"), body: { jobs: [] } },
    ]);
    renderAppAt(runPath(WRITABLE_ID, "test-job-absent"));
    expect(await screen.findByText("Ce run n'est pas disponible")).toBeInTheDocument();
  });
});

describe("NEEDS_REVIEW is a hard blocker", () => {
  it("blocks execution with no way through", async () => {
    backend({
      job: { ...DRY_RUN_JOB_WIRE, status: "NEEDS_REVIEW" },
      plan: PLAN_NEEDS_REVIEW_WIRE,
    });
    renderAppAt(runPath(WRITABLE_ID, DRY_RUN_JOB_WIRE.job_id));

    expect(await screen.findByText("Plan à vérifier — exécution bloquée")).toBeInTheDocument();
    expect(screen.getByText("Aucune écriture")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Autoriser/ })).toBeNull();
    expect(screen.queryByRole("checkbox")).toBeNull();
    for (const bypass of [/continuer/i, /forcer/i, /ignorer/i, /malgré/i]) {
      expect(screen.queryByRole("button", { name: bypass })).toBeNull();
    }
  });

  it("shows the reasons the backend gave", async () => {
    backend({
      job: { ...DRY_RUN_JOB_WIRE, status: "NEEDS_REVIEW" },
      plan: PLAN_NEEDS_REVIEW_WIRE,
    });
    renderAppAt(runPath(WRITABLE_ID, DRY_RUN_JOB_WIRE.job_id));

    expect(await screen.findByText("RUBRIQUE_AMBIGUE")).toBeInTheDocument();
    expect(screen.getByText("deux correspondances possibles")).toBeInTheDocument();
    expect(screen.getByText("MONTANT_ABSENT")).toBeInTheDocument();
  });
});

describe("IDENTITY_FAILED is a hard blocker", () => {
  it("offers no execution and no portal evidence", async () => {
    backend({ job: { ...DRY_RUN_JOB_WIRE, status: "IDENTITY_FAILED" } });
    renderAppAt(runPath(WRITABLE_ID, DRY_RUN_JOB_WIRE.job_id));

    expect(
      await screen.findByText("Identité non confirmée — exécution bloquée"),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Autoriser/ })).toBeNull();
    expect(screen.queryByRole("checkbox")).toBeNull();
  });
});

describe("plan review", () => {
  it("renders the plan exactly as the backend sent it", async () => {
    backend({ job: DRY_RUN_JOB_WIRE });
    renderAppAt(runPath(WRITABLE_ID, DRY_RUN_JOB_WIRE.job_id));

    expect(await screen.findByText("RUB-TEST-1")).toBeInTheDocument();
    // Decimal strings survive untouched: "1200.50", not 1200.5.
    expect(screen.getByText("1200.50")).toBeInTheDocument();
    expect(screen.getByText("0.00")).toBeInTheDocument();
    expect(screen.getByText("valeur-test-1")).toBeInTheDocument();
  });

  it("uses the corrected plan wording and real counts", async () => {
    backend({ job: DRY_RUN_JOB_WIRE });
    renderAppAt(runPath(WRITABLE_ID, DRY_RUN_JOB_WIRE.job_id));

    expect(
      await screen.findByText(
        /L'agent saisira les rubriques et champs présentés dans ce plan, puis s'arrêtera pour vérification humaine\./,
      ),
    ).toBeInTheDocument();
    // Counts come from the plan, so they appear once it has loaded.
    expect((await screen.findAllByText(/2 rubriques · 2 champs/)).length).toBeGreaterThan(0);
  });

  it("fabricates no approver, no duration and no total", async () => {
    backend({ job: DRY_RUN_JOB_WIRE });
    renderAppAt(runPath(WRITABLE_ID, DRY_RUN_JOB_WIRE.job_id));

    await screen.findByText("RUB-TEST-1");
    const text = document.body.textContent ?? "";
    expect(text).not.toMatch(/approuvé par/i);
    expect(text).not.toMatch(/Total HT/i);
    expect(text).not.toMatch(/\bdurée\b/i);
    expect(text).not.toMatch(/%/);
  });
});

describe("execution authorization", () => {
  it("requires an explicit confirmation before it can be used", async () => {
    setCsrfCookie();
    backend({ job: DRY_RUN_JOB_WIRE });
    const user = userEvent.setup();
    renderAppAt(runPath(WRITABLE_ID, DRY_RUN_JOB_WIRE.job_id));

    const button = await screen.findByRole("button", { name: "Autoriser le remplissage" });
    expect(button).toBeDisabled();
    await user.click(screen.getByRole("checkbox"));
    expect(button).toBeEnabled();
  });

  it("posts only an idempotency key and routes to the new execution job", async () => {
    setCsrfCookie();
    const stub = backend({ job: DRY_RUN_JOB_WIRE });
    const user = userEvent.setup();
    renderAppAt(runPath(WRITABLE_ID, DRY_RUN_JOB_WIRE.job_id));

    await user.click(await screen.findByRole("checkbox"));
    await user.click(screen.getByRole("button", { name: "Autoriser le remplissage" }));

    await waitFor(() => {
      const posted = stub.mock.calls.find(([url]) => (url as string).includes("/executions"));
      expect(posted?.[0]).toBe(`/jobs/${DRY_RUN_JOB_WIRE.job_id}/executions`);
      const body = JSON.parse((posted?.[1] as RequestInit).body as string) as Record<
        string,
        unknown
      >;
      expect(Object.keys(body)).toEqual(["idempotency_key"]);
      expect(body).not.toHaveProperty("account_id");
      expect(body).not.toHaveProperty("mode");
      expect(body).not.toHaveProperty("workflow_name");
    });
  });

  it("surfaces a refusal without exposing the backend message", async () => {
    setCsrfCookie();
    backend({ job: DRY_RUN_JOB_WIRE, executionStatus: 409 });
    const user = userEvent.setup();
    renderAppAt(runPath(WRITABLE_ID, DRY_RUN_JOB_WIRE.job_id));

    await user.click(await screen.findByRole("checkbox"));
    await user.click(screen.getByRole("button", { name: "Autoriser le remplissage" }));

    await screen.findByRole("alert");
    expect(document.body.textContent).not.toContain("not an approved dry-run");
  });
});

describe("execution created", () => {
  it("shows the execution as its own run, distinct from the dry run", async () => {
    backend({ job: EXECUTION_JOB_WIRE });
    renderAppAt(runPath(WRITABLE_ID, EXECUTION_JOB_WIRE.job_id));

    expect(
      await screen.findByText(/Accès au compte portail en cours d'acquisition/),
    ).toBeInTheDocument();
    // No progress invented for a run whose backend state is all we know.
    expect(document.body.textContent).not.toMatch(/%/);
    expect(screen.queryByRole("progressbar")).toBeNull();
  });
});
