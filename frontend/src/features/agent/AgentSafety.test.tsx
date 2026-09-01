import { describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderAppAt, createTestQueryClient } from "../../test/renderApp";
import { mockRoutes, setCsrfCookie } from "../../test/apiMock";
import {
  DRY_RUN_JOB_WIRE,
  EXECUTION_JOB_WIRE,
  PLAN_NEEDS_REVIEW_WIRE,
  PLAN_WIRE,
  READ_ONLY_ACCOUNT_WIRE,
  SECOND_WRITABLE_ACCOUNT_WIRE,
  SYNTHETIC_DOSSIER,
  TEST_ACCOUNTS_WIRE,
  WRITABLE_ACCOUNT_WIRE,
} from "../../test/fixtures";

const A = WRITABLE_ACCOUNT_WIRE.account_id;
const B = SECOND_WRITABLE_ACCOUNT_WIRE.account_id;
const JOB = DRY_RUN_JOB_WIRE.job_id;
const runPath = (accountId: string, jobId: string) =>
  `/accounts/${accountId}/agent/runs/${jobId}`;
const agentPath = (accountId: string) => `/accounts/${accountId}/agent`;

const AUTHORIZE = "Autoriser le remplissage";

interface Options {
  readonly job?: unknown;
  readonly plan?: unknown;
  readonly planStatus?: number;
}

function backend(options: Options = {}) {
  return mockRoutes([
    { match: (url) => url.startsWith("/accounts"), body: { accounts: TEST_ACCOUNTS_WIRE } },
    {
      match: (url, init) => url.includes("/executions") && init.method === "POST",
      body: { job_id: EXECUTION_JOB_WIRE.job_id, status: "QUEUED" },
    },
    {
      match: (url, init) => url === "/jobs/dry-runs" && init.method === "POST",
      body: { job_id: JOB, status: "QUEUED" },
    },
    {
      match: (url) => url.includes("/plan"),
      status: options.planStatus ?? 200,
      body:
        (options.planStatus ?? 200) === 200
          ? (options.plan ?? PLAN_WIRE)
          : { error: "PLAN_INPUT_UNAVAILABLE", message: "gone", correlation_id: "0" },
    },
    // Account-blind, as GET /jobs?job_id= is: it returns whatever that job
    // actually is, and the frontend must notice when that is another
    // account's job.
    { match: (url) => url.startsWith("/jobs"), body: { jobs: [options.job ?? DRY_RUN_JOB_WIRE] } },
  ]);
}

describe("authorization requires the exact reviewed plan", () => {
  it("offers no authorization while the plan is still loading", async () => {
    // The plan request never settles, so the screen stays in its loading
    // state for the whole test.
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        if (url.includes("/plan")) return new Promise<Response>(() => {});
        const body = url.startsWith("/accounts")
          ? { accounts: TEST_ACCOUNTS_WIRE }
          : { jobs: [DRY_RUN_JOB_WIRE] };
        return Promise.resolve({
          ok: true,
          status: 200,
          text: () => Promise.resolve(JSON.stringify(body)),
        } as unknown as Response);
      }),
    );

    renderAppAt(runPath(A, JOB));

    expect(
      await screen.findByText(/L'autorisation ne sera proposée qu'une fois le plan affiché/),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: AUTHORIZE })).toBeNull();
    expect(screen.queryByRole("checkbox")).toBeNull();
  });

  it("offers no authorization when the plan request fails", async () => {
    backend({ planStatus: 410 });
    renderAppAt(runPath(A, JOB));

    expect(await screen.findByText("Impossible de charger le plan")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: AUTHORIZE })).toBeNull();
    expect(screen.queryByRole("checkbox")).toBeNull();
  });

  it("offers no authorization when the plan names another job", async () => {
    backend({ plan: { ...PLAN_WIRE, job_id: "test-job-other" } });
    renderAppAt(runPath(A, JOB));

    await screen.findByText("Aucune écriture n’a été effectuée sur SinAuto.");
    await waitFor(() => expect(screen.queryByRole("checkbox")).toBeNull());
    expect(screen.queryByRole("button", { name: AUTHORIZE })).toBeNull();
  });

  it("offers no authorization when the plan hash differs from the verified job", async () => {
    backend({ plan: { ...PLAN_WIRE, plan_hash: "f".repeat(64) } });
    renderAppAt(runPath(A, JOB));

    expect(
      await screen.findByText("Le plan affiché ne correspond pas à ce run"),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: AUTHORIZE })).toBeNull();
    expect(screen.queryByRole("checkbox")).toBeNull();
  });

  it("offers no authorization when the job records no plan hash", async () => {
    backend({ job: { ...DRY_RUN_JOB_WIRE, plan_hash: null } });
    renderAppAt(runPath(A, JOB));

    expect(
      await screen.findByText("Le plan affiché ne correspond pas à ce run"),
    ).toBeInTheDocument();
    expect(screen.queryByRole("checkbox")).toBeNull();
  });

  it("offers no authorization when a verified plan unexpectedly carries review items", async () => {
    backend({ plan: PLAN_NEEDS_REVIEW_WIRE });
    renderAppAt(runPath(A, JOB));

    expect(
      await screen.findByText("Le plan affiché ne correspond pas à ce run"),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: AUTHORIZE })).toBeNull();
  });

  it("offers authorization only once the exact reviewed plan is on screen", async () => {
    backend();
    renderAppAt(runPath(A, JOB));

    // The plan is visible...
    expect(await screen.findByText("RUB-TEST-1")).toBeInTheDocument();
    // ...and only then is the gate present.
    expect(await screen.findByRole("button", { name: AUTHORIZE })).toBeDisabled();
    expect(screen.getByRole("checkbox")).toBeInTheDocument();
  });
});

describe("job cache is account-scoped", () => {
  it("does not serve a job cached under one account beneath another", async () => {
    // One client across both visits: a key of ["job", jobId] alone would hand
    // account A's cached job straight to account B.
    const client = createTestQueryClient();
    backend({ job: DRY_RUN_JOB_WIRE });

    const first = renderAppAt(runPath(A, JOB), client);
    expect(await screen.findByText("RUB-TEST-1")).toBeInTheDocument();
    first.unmount();

    renderAppAt(runPath(B, JOB), client);

    // The job belongs to account A, so under B it must fail closed rather
    // than render from cache.
    expect(await screen.findByText("Impossible de charger ce run")).toBeInTheDocument();
    expect(screen.queryByText("RUB-TEST-1")).toBeNull();
    expect(screen.queryByRole("button", { name: AUTHORIZE })).toBeNull();
  });
});

describe("state resets when the run identity changes", () => {
  it("starts the confirmation unchecked on a different job", async () => {
    setCsrfCookie();
    const user = userEvent.setup();
    const otherJob = { ...DRY_RUN_JOB_WIRE, job_id: "test-job-dry-2" };
    mockRoutes([
      { match: (url) => url.startsWith("/accounts"), body: { accounts: TEST_ACCOUNTS_WIRE } },
      {
        match: (url) => url.includes("/plan"),
        body: (url: string) => ({
          ...PLAN_WIRE,
          job_id: url.includes("test-job-dry-2") ? "test-job-dry-2" : JOB,
        }),
      },
      {
        match: (url) => url.startsWith("/jobs"),
        body: (url: string) => ({
          jobs: [new URL(url, "http://localhost").searchParams.get("job_id") === "test-job-dry-2" ? otherJob : DRY_RUN_JOB_WIRE],
        }),
      },
    ]);

    const client = createTestQueryClient();
    const first = renderAppAt(runPath(A, JOB), client);
    await user.click(await screen.findByRole("checkbox"));
    expect(screen.getByRole("checkbox")).toBeChecked();
    first.unmount();

    renderAppAt(runPath(A, "test-job-dry-2"), client);
    expect(await screen.findByRole("checkbox")).not.toBeChecked();
    expect(screen.getByRole("button", { name: AUTHORIZE })).toBeDisabled();
  });

  it("requires a fresh dossier after the account changes", async () => {
    setCsrfCookie();
    const user = userEvent.setup();
    const stub = backend();
    const client = createTestQueryClient();

    const first = renderAppAt(agentPath(A), client);
    await screen.findByRole("heading", { name: "Nouveau run" });
    const file = new File([JSON.stringify(SYNTHETIC_DOSSIER)], "dossier-test.json", {
      type: "application/json",
    });
    Object.defineProperty(file, "text", {
      value: () => Promise.resolve(JSON.stringify(SYNTHETIC_DOSSIER)),
    });
    await user.upload(screen.getByLabelText("Fichier JSON"), file);
    await screen.findByText(/Fichier prêt/);
    first.unmount();

    // A dossier is chosen for one explicit account.
    renderAppAt(agentPath(B), client);
    await screen.findByRole("heading", { name: "Nouveau run" });
    expect(screen.queryByText(/Fichier prêt/)).toBeNull();
    expect(screen.getByRole("button", { name: "Préparer le plan" })).toBeDisabled();
    expect(stub.mock.calls.some(([url]) => url === "/jobs/dry-runs")).toBe(false);
  });
});

describe("execution planning that stops before writing", () => {
  it("shows a hard blocker for an EXECUTE job in NEEDS_REVIEW", async () => {
    backend({ job: { ...EXECUTION_JOB_WIRE, status: "NEEDS_REVIEW" } });
    renderAppAt(runPath(A, EXECUTION_JOB_WIRE.job_id));

    expect(await screen.findByText("Plan à vérifier — exécution bloquée")).toBeInTheDocument();
    expect(screen.getByText("Aucune écriture")).toBeInTheDocument();
    // None of the forward-looking copy may appear.
    expect(screen.queryByText(/L'agent remplira la mission ouverte/)).toBeNull();
    expect(screen.queryByText(/Le remplissage a été autorisé/)).toBeNull();
    expect(screen.queryByRole("button", { name: AUTHORIZE })).toBeNull();
    expect(screen.queryByRole("checkbox")).toBeNull();
  });

  it("does not promise further filling for any stopped execution", async () => {
    const stopped = [
      ["WRITE_ABORTED", /Le remplissage a été interrompu/],
      ["ERROR", /Le run s'est terminé en échec/],
      ["ABORTED_ON_RESTART", /abandonné au redémarrage/],
      ["INTERRUPTED_NEEDS_HUMAN_REVIEW", /interrompu et demande une vérification humaine/],
    ] as const;

    for (const [status, expected] of stopped) {
      backend({ job: { ...EXECUTION_JOB_WIRE, status } });
      const view = renderAppAt(runPath(A, EXECUTION_JOB_WIRE.job_id));
      expect(await screen.findByText(expected)).toBeInTheDocument();
      expect(screen.queryByText(/L'agent remplira la mission ouverte/)).toBeNull();
      view.unmount();
    }
  });

  it("keeps the forward-looking sentence only while the run is really moving", async () => {
    backend({ job: EXECUTION_JOB_WIRE });
    renderAppAt(runPath(A, EXECUTION_JOB_WIRE.job_id));

    expect(
      await screen.findByText(
        "L'agent remplira la mission ouverte, puis s'arrêtera pour vérification humaine.",
      ),
    ).toBeInTheDocument();
  });

  it("says the agent has stopped when a person is expected to take over", async () => {
    backend({ job: { ...EXECUTION_JOB_WIRE, status: "READY_FOR_HUMAN_REVIEW" } });
    renderAppAt(runPath(A, EXECUTION_JOB_WIRE.job_id));

    expect(await screen.findByText(/L'agent s'est arrêté/)).toBeInTheDocument();
    expect(screen.queryByText(/L'agent remplira la mission ouverte/)).toBeNull();
  });
});

describe("read-only accounts are unaffected by these gates", () => {
  it("still refuses a run URL on a MAMDA account", async () => {
    backend();
    renderAppAt(runPath(READ_ONLY_ACCOUNT_WIRE.account_id, JOB));
    expect(await screen.findByText("Ce compte est en lecture seule")).toBeInTheDocument();
  });
});
