import { describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderAppAt } from "../../test/renderApp";
import { mockRoutes, setCsrfCookie } from "../../test/apiMock";
import {
  DRY_RUN_JOB_WIRE,
  EXECUTION_JOB_WIRE,
  PLAN_WIRE,
  READ_ONLY_ACCOUNT_WIRE,
  SECOND_WRITABLE_ACCOUNT_WIRE,
  TEST_ACCOUNTS_WIRE,
  WRITABLE_ACCOUNT_WIRE,
} from "../../test/fixtures";
import { accountAgentJobPath } from "@shared/utils/routes";

const A = WRITABLE_ACCOUNT_WIRE.account_id;
const B = SECOND_WRITABLE_ACCOUNT_WIRE.account_id;
const runPath = (accountId: string, jobId: string) =>
  `/accounts/${accountId}/agent/runs/${jobId}`;

/** The execution job of the second writable account. */
const OTHER_EXECUTION = {
  ...EXECUTION_JOB_WIRE,
  job_id: "test-job-exec-2",
  account_id: B,
  status: "READY_FOR_HUMAN_REVIEW",
  created_at: "2026-01-15T10:00:00Z",
  finished_at: null,
};

function backend(jobs: readonly unknown[], handoffStatus = 200) {
  return mockRoutes([
    { match: (url) => url.startsWith("/accounts"), body: { accounts: TEST_ACCOUNTS_WIRE } },
    {
      match: (url, init) =>
        (url.includes("/review-completed") || url.includes("/problem")) && init.method === "POST",
      status: handoffStatus,
      body:
        handoffStatus === 200
          ? { job_id: EXECUTION_JOB_WIRE.job_id, status: "HUMAN_CONFIRMED_COMPLETE" }
          : {
              error: "REVIEW_NOT_AWAITING_CONFIRMATION",
              message: "the job cannot be confirmed completed right now",
              correlation_id: "0",
            },
    },
    { match: (url) => url.includes("/plan"), body: PLAN_WIRE },
    { match: (url) => url.startsWith("/claims"), body: { claims: [] } },
    {
      match: (url) => url.startsWith("/jobs"),
      body: (url: string) => {
        const wanted = new URL(url, "http://localhost").searchParams.get("job_id");
        if (wanted === null) return { jobs };
        return { jobs: jobs.filter((job) => (job as { job_id: string }).job_id === wanted) };
      },
    },
  ]);
}

describe("global active-run banner", () => {
  it("shows nothing when no execution is active", async () => {
    backend([{ ...EXECUTION_JOB_WIRE, status: "HUMAN_CONFIRMED_COMPLETE" }]);
    renderAppAt("/overview");

    await screen.findByRole("heading", { name: "Vue d'ensemble" });
    await waitFor(() =>
      expect(screen.queryByRole("complementary", { name: "Runs en cours" })).toBeNull(),
    );
  });

  it("shows an active execution with its own account, not the one being viewed", async () => {
    backend([{ ...EXECUTION_JOB_WIRE, status: "WRITING" }]);
    // Viewing account B while the run belongs to account A.
    renderAppAt(`/accounts/${B}/work`);

    const banner = await screen.findByRole("complementary", { name: "Runs en cours" });
    expect(banner).toHaveTextContent("MCMA • ZONE-A");
    expect(banner).toHaveTextContent("Remplissage en cours");
    // And the link returns to the run's own account.
    expect(screen.getByRole("link", { name: "Ouvrir le run" })).toHaveAttribute(
      "href",
      accountAgentJobPath(A, EXECUTION_JOB_WIRE.job_id),
    );
  });

  it("lists every active run rather than picking one", async () => {
    backend([{ ...EXECUTION_JOB_WIRE, status: "WRITING" }, OTHER_EXECUTION]);
    renderAppAt("/overview");

    const banner = await screen.findByRole("complementary", { name: "Runs en cours" });
    expect(banner).toHaveTextContent("2 runs d'exécution en cours");
    expect(banner).toHaveTextContent("MCMA • ZONE-A");
    expect(banner).toHaveTextContent("MCMA • ZONE-C");
    expect(screen.getAllByRole("link", { name: "Ouvrir le run" })).toHaveLength(2);
  });

  it("keeps AWAITING_HUMAN_CONFIRMATION on the banner", async () => {
    // Not semantically complete: the account is still held until a person
    // confirms or reports a problem.
    backend([{ ...EXECUTION_JOB_WIRE, status: "AWAITING_HUMAN_CONFIRMATION" }]);
    renderAppAt("/overview");

    const banner = await screen.findByRole("complementary", { name: "Runs en cours" });
    expect(banner).toHaveTextContent("En attente de confirmation");
    expect(banner).toHaveTextContent("Action requise");
  });

  it("excludes genuine outcomes", async () => {
    for (const status of ["HUMAN_CONFIRMED_COMPLETE", "ERROR", "WRITE_ABORTED"] as const) {
      backend([{ ...EXECUTION_JOB_WIRE, status }]);
      const view = renderAppAt("/overview");
      await screen.findByRole("heading", { name: "Vue d'ensemble" });
      await waitFor(() =>
        expect(screen.queryByRole("complementary", { name: "Runs en cours" })).toBeNull(),
      );
      view.unmount();
    }
  });

  it("does not let a dry run masquerade as a write execution", async () => {
    backend([{ ...DRY_RUN_JOB_WIRE, status: "PLANNING" }]);
    renderAppAt("/overview");

    await screen.findByRole("heading", { name: "Vue d'ensemble" });
    await waitFor(() =>
      expect(screen.queryByRole("complementary", { name: "Runs en cours" })).toBeNull(),
    );
  });

  it("never shows an opaque account id when the account is unknown", async () => {
    backend([{ ...EXECUTION_JOB_WIRE, account_id: "test-account-not-visible", status: "WRITING" }]);
    renderAppAt("/overview");

    const banner = await screen.findByRole("complementary", { name: "Runs en cours" });
    // The account list has loaded and does not contain it: that is not
    // "still loading", and the opaque id is never shown instead.
    await waitFor(() => expect(banner).toHaveTextContent("Compte indisponible"));
    expect(banner).not.toHaveTextContent("test-account-not-visible");
    expect(banner).not.toHaveTextContent("Compte en cours de chargement");
    // No link to a run whose account cannot be named.
    expect(screen.queryByRole("link", { name: "Ouvrir le run" })).toBeNull();
  });

  it("reports a failed job read instead of implying nothing is running", async () => {
    mockRoutes([
      { match: (url) => url.startsWith("/accounts"), body: { accounts: TEST_ACCOUNTS_WIRE } },
      { match: (url) => url.startsWith("/claims"), body: { claims: [] } },
      {
        match: (url) => url.startsWith("/jobs"),
        status: 500,
        body: { error: "INTERNAL_ERROR", message: "sqlite is unhappy", correlation_id: "0" },
      },
    ]);
    renderAppAt("/overview");

    const banner = await screen.findByRole("complementary", { name: "Runs en cours" });
    expect(banner).toHaveTextContent("Impossible de vérifier les runs actifs.");
    // An outage must not read as "the agent is idle".
    expect(banner).toHaveTextContent(/ne peut pas confirmer qu'aucun run n'est en cours/);
    expect(banner.textContent ?? "").not.toContain("sqlite is unhappy");
    expect(screen.queryByRole("link", { name: "Ouvrir le run" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Relancer|Réessayer/ })).toBeNull();
  });

  it("invents no progress figure or estimate", async () => {
    backend([{ ...EXECUTION_JOB_WIRE, status: "WRITING" }]);
    renderAppAt("/overview");

    const banner = await screen.findByRole("complementary", { name: "Runs en cours" });
    expect(banner.textContent ?? "").not.toMatch(/%|restant|secondes|minutes|\bETA\b/i);
  });
});

describe("READY_FOR_HUMAN_REVIEW", () => {
  const readyJob = { ...EXECUTION_JOB_WIRE, status: "READY_FOR_HUMAN_REVIEW", finished_at: null };

  it("states the exact handoff and safety copy", async () => {
    backend([readyJob]);
    renderAppAt(runPath(A, EXECUTION_JOB_WIRE.job_id));

    expect(
      await screen.findByText("L'agent s'est arrêté. Vérifiez le dossier dans SinAuto."),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Aucune validation finale ni clôture n'a été effectuée automatiquement. Vérifiez les saisies dans SinAuto avant de poursuivre manuellement.",
      ),
    ).toBeInTheDocument();
    // The panel heading and the "action requise" tag both carry it.
    expect(screen.getAllByText(/Vérification à faire/).length).toBeGreaterThan(0);
  });

  it("does not offer confirmation before the browser has closed", async () => {
    // The backend refuses review-completed from this status, so the action is
    // absent rather than present-and-doomed.
    backend([readyJob]);
    renderAppAt(runPath(A, EXECUTION_JOB_WIRE.job_id));

    await screen.findByText("L'agent s'est arrêté. Vérifiez le dossier dans SinAuto.");
    expect(screen.queryByRole("button", { name: /Confirmer la vérification/ })).toBeNull();
    expect(
      screen.getByText("La confirmation vous sera demandée une fois la fenêtre SinAuto fermée."),
    ).toBeInTheDocument();
  });

  it("allows reporting a problem", async () => {
    setCsrfCookie();
    const stub = backend([readyJob]);
    const user = userEvent.setup();
    renderAppAt(runPath(A, EXECUTION_JOB_WIRE.job_id));

    await user.click(await screen.findByRole("button", { name: "Signaler un problème" }));

    await waitFor(() => {
      const posted = stub.mock.calls.find(([url]) => (url as string).includes("/problem"));
      expect(posted?.[0]).toBe(`/jobs/${EXECUTION_JOB_WIRE.job_id}/problem`);
      expect(JSON.parse((posted?.[1] as RequestInit).body as string)).toEqual({});
    });
  });

  it("keeps the manual SinAuto steps and offers no confirmation", async () => {
    backend([readyJob]);
    renderAppAt(runPath(A, EXECUTION_JOB_WIRE.job_id));

    await screen.findByText("L'agent s'est arrêté. Vérifiez le dossier dans SinAuto.");
    expect(
      screen.getByText("Fermez la fenêtre SinAuto lorsque vous avez terminé."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Relisez les saisies de l'agent dans la fenêtre SinAuto."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Confirmer la vérification" })).toBeNull();
    // And it does not claim the window is already closed.
    expect(screen.queryByText(/La fenêtre SinAuto est fermée/)).toBeNull();
  });

  it("shows no portal action and no fabricated finish time", async () => {
    backend([readyJob]);
    renderAppAt(runPath(A, EXECUTION_JOB_WIRE.job_id));

    await screen.findByText("L'agent s'est arrêté. Vérifiez le dossier dans SinAuto.");
    for (const forbidden of ["Valider", "Clôturer", "Enregistrer SinAuto", "Finaliser", "GED"]) {
      expect(screen.queryByRole("button", { name: new RegExp(forbidden) })).toBeNull();
    }
    // finishedAt is legitimately null here.
    expect(screen.queryByText(/Terminé à/)).toBeNull();
  });
});

describe("AWAITING_HUMAN_CONFIRMATION", () => {
  const awaitingJob = {
    ...EXECUTION_JOB_WIRE,
    status: "AWAITING_HUMAN_CONFIRMATION",
    finished_at: null,
  };

  it("offers both application actions in a confirmation state", async () => {
    backend([awaitingJob]);
    renderAppAt(runPath(A, EXECUTION_JOB_WIRE.job_id));

    expect(
      await screen.findByRole("button", { name: "Confirmer la vérification" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Signaler un problème" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Confirmation requise" })).toBeInTheDocument();
    expect(
      screen.getByText(
        "La fenêtre SinAuto est fermée. Confirmez maintenant que votre vérification humaine est terminée, ou signalez un problème.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Elles ne déclenchent aucune action dans SinAuto/),
    ).toBeInTheDocument();
  });

  it("does not repeat the READY instructions about the browser", async () => {
    // The window is already closed; telling someone to inspect and close it
    // again contradicts the sentence directly above.
    backend([awaitingJob]);
    renderAppAt(runPath(A, EXECUTION_JOB_WIRE.job_id));

    await screen.findByRole("button", { name: "Confirmer la vérification" });
    expect(screen.queryByText("Fermez la fenêtre SinAuto lorsque vous avez terminé.")).toBeNull();
    expect(
      screen.queryByText("L'agent s'est arrêté. Vérifiez le dossier dans SinAuto."),
    ).toBeNull();
    expect(
      screen.queryByText("Relisez les saisies de l'agent dans la fenêtre SinAuto."),
    ).toBeNull();
    expect(screen.queryByText(/Ce qu'il vous reste à faire/)).toBeNull();
  });

  it("posts an empty body with no client-settable authority fields", async () => {
    setCsrfCookie();
    const stub = backend([awaitingJob]);
    const user = userEvent.setup();
    renderAppAt(runPath(A, EXECUTION_JOB_WIRE.job_id));

    await user.click(await screen.findByRole("button", { name: "Confirmer la vérification" }));

    await waitFor(() => {
      const posted = stub.mock.calls.find(([url]) =>
        (url as string).includes("/review-completed"),
      );
      expect(posted?.[0]).toBe(`/jobs/${EXECUTION_JOB_WIRE.job_id}/review-completed`);
      const body = JSON.parse((posted?.[1] as RequestInit).body as string) as Record<
        string,
        unknown
      >;
      expect(body).toEqual({});
      for (const field of ["account_id", "user_id", "confirmed_by_user_id", "status"]) {
        expect(body).not.toHaveProperty(field);
      }
      expect((posted?.[1] as RequestInit).credentials).toBe("include");
      expect(
        ((posted?.[1] as RequestInit).headers as Record<string, string>)["X-CSRF-Token"],
      ).toBeDefined();
    });
  });

  it("does not claim completion optimistically when the backend refuses", async () => {
    setCsrfCookie();
    backend([awaitingJob], 409);
    const user = userEvent.setup();
    renderAppAt(runPath(A, EXECUTION_JOB_WIRE.job_id));

    await user.click(await screen.findByRole("button", { name: "Confirmer la vérification" }));

    await screen.findByRole("alert");
    expect(screen.queryByText("Vérification confirmée")).toBeNull();
    // The raw backend sentence is not rendered.
    expect(document.body.textContent).not.toContain("cannot be confirmed completed right now");
  });
});

describe("HUMAN_CONFIRMED_COMPLETE", () => {
  it("claims only that the human review was recorded", async () => {
    backend([{ ...EXECUTION_JOB_WIRE, status: "HUMAN_CONFIRMED_COMPLETE" }]);
    renderAppAt(runPath(A, EXECUTION_JOB_WIRE.job_id));

    expect(await screen.findByText("Votre vérification humaine a été enregistrée.")).toBeInTheDocument();
    expect(
      screen.getByText(/Cette application n'a pas constaté elle-même de validation ou de clôture/),
    ).toBeInTheDocument();
    const text = document.body.textContent ?? "";
    expect(text).not.toMatch(/dossier clôturé|validé dans SinAuto|clôture réussie/i);
  });
});

describe("live execution stages", () => {
  it("names each stage truthfully with no progress figure", async () => {
    const stages = [
      ["ACQUIRING_ACCOUNT_LOCK", /Accès au compte portail en cours d'acquisition/],
      ["IDENTITY_VERIFYING", /Vérification de l'identité de la mission/],
      ["IDENTITY_VERIFIED", /Identité confirmée/],
      ["WRITING", /Remplissage des rubriques et des champs/],
      ["VERIFYING", /Relecture des saisies effectuées/],
    ] as const;

    for (const [status, expected] of stages) {
      backend([{ ...EXECUTION_JOB_WIRE, status }]);
      const view = renderAppAt(runPath(A, EXECUTION_JOB_WIRE.job_id));
      expect(await screen.findByText(expected)).toBeInTheDocument();
      const text = document.body.textContent ?? "";
      expect(text).not.toMatch(/%|restant|\bETA\b|champs écrits/i);
      expect(screen.queryByRole("progressbar")).toBeNull();
      view.unmount();
    }
  });

  it("loads a run from GET on a deep link, with no event needed", async () => {
    backend([{ ...EXECUTION_JOB_WIRE, status: "WRITING" }]);
    renderAppAt(runPath(A, EXECUTION_JOB_WIRE.job_id));
    expect(
      await screen.findByText(/Remplissage des rubriques et des champs/),
    ).toBeInTheDocument();
  });
});

describe("MAMDA remains structurally denied", () => {
  it("refuses the run route on a read-only account", async () => {
    backend([EXECUTION_JOB_WIRE]);
    renderAppAt(runPath(READ_ONLY_ACCOUNT_WIRE.account_id, EXECUTION_JOB_WIRE.job_id));
    expect(await screen.findByText("Ce compte est en lecture seule")).toBeInTheDocument();
  });

  it("offers no agent route for a write execution on a read-only account", async () => {
    // This state should be impossible — MAMDA automation is refused
    // server-side. If it is ever reported, the anomaly is shown rather than
    // hidden, but no agent action is offered for it.
    backend([
      { ...EXECUTION_JOB_WIRE, account_id: READ_ONLY_ACCOUNT_WIRE.account_id, status: "WRITING" },
    ]);
    renderAppAt("/overview");

    const banner = await screen.findByRole("complementary", { name: "Runs en cours" });
    expect(banner).toHaveTextContent("MAMDA • ZONE-B");
    expect(banner).toHaveTextContent("Exécution incohérente — compte en lecture seule");
    expect(screen.queryByRole("link", { name: "Ouvrir le run" })).toBeNull();
    // No agent path for that account appears anywhere on screen.
    const agentPath = accountAgentJobPath(
      READ_ONLY_ACCOUNT_WIRE.account_id,
      EXECUTION_JOB_WIRE.job_id,
    );
    for (const link of screen.queryAllByRole("link")) {
      expect(link.getAttribute("href")).not.toBe(agentPath);
    }
    expect(banner).not.toHaveTextContent(READ_ONLY_ACCOUNT_WIRE.account_id);
  });
});

describe("privacy", () => {
  it("logs nothing while rendering runs", async () => {
    const log = vi.spyOn(console, "log").mockImplementation(() => {});
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    backend([{ ...EXECUTION_JOB_WIRE, status: "WRITING" }]);
    renderAppAt(runPath(A, EXECUTION_JOB_WIRE.job_id));

    await screen.findByText(/Remplissage des rubriques et des champs/);
    expect(log).not.toHaveBeenCalled();
    expect(warn).not.toHaveBeenCalled();
    expect(window.localStorage.length).toBe(0);
  });
});
