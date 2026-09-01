import { expect, test } from "@playwright/test";

/**
 * These prove things a unit test cannot: that a real browser, loading the
 * real build from the real server, gets a working application — and that the
 * serving layer does not quietly break the two things the product depends on
 * (route precedence and the CSP).
 *
 * They deliberately do not re-test component logic. Where a fact is already
 * pinned by the Vitest suite, the E2E only checks that it survives the round
 * trip through FastAPI.
 */

const MCMA_A = "e2e-acct-mcma-a";
const MAMDA_A = "e2e-acct-mamda-a";
const READY_JOB = "e2e-job-ready";
const AWAITING_JOB = "e2e-job-awaiting";

test("the root address loads the V2 application, not the old dashboard", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("link", { name: "MCMA Operations" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Vue d'ensemble" })).toBeVisible();
  // The V1 shell had no account rail.
  await expect(page.getByRole("navigation", { name: "Comptes portail" })).toBeVisible();
});

test("the account rail renders the accounts the backend returned", async ({ page }) => {
  await page.goto("/overview");
  // Scoped to the rail: account identity also appears in the active-run
  // banner, which is correct behaviour and not what this test is about.
  const rail = page.getByRole("navigation", { name: "Comptes portail" });
  await expect(rail.getByText("MCMA • ZONE-A")).toBeVisible();
  await expect(rail.getByText("MAMDA • ZONE-A")).toBeVisible();
  // Opaque identifiers are never employee-facing copy, anywhere on the page.
  await expect(page.getByText(MCMA_A)).toHaveCount(0);
});

test("a read-only account offers no agent entry and refuses the agent route", async ({ page }) => {
  await page.goto(`/accounts/${MAMDA_A}/work`);
  await expect(page.getByRole("heading", { name: "File de travail" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Agent dossier" })).toHaveCount(0);

  // Typed directly, the route still fails closed.
  await page.goto(`/accounts/${MAMDA_A}/agent`);
  await expect(page.getByText("Ce compte est en lecture seule")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Nouveau run" })).toHaveCount(0);
});

test("a writable account reaches the agent", async ({ page }) => {
  await page.goto(`/accounts/${MCMA_A}/agent`);
  await expect(page.getByRole("heading", { name: "Nouveau run" })).toBeVisible();
  await expect(page.getByLabel("Fichier JSON")).toBeVisible();
});

test("a deep link survives a full browser reload", async ({ page }) => {
  const deepLink = `/accounts/${MCMA_A}/agent/runs/${READY_JOB}`;
  await page.goto(deepLink);
  await expect(page.getByText("L'agent s'est arrêté. Vérifiez le dossier dans SinAuto.")).toBeVisible();

  await page.reload();
  expect(page.url()).toContain(deepLink);
  await expect(page.getByText("L'agent s'est arrêté. Vérifiez le dossier dans SinAuto.")).toBeVisible();
});

test("the active-run banner keeps each run on its own account", async ({ page }) => {
  // Viewing a different account than the one the runs belong to.
  await page.goto(`/accounts/${MAMDA_A}/work`);
  const banner = page.getByRole("complementary", { name: "Runs en cours" });
  await expect(banner).toBeVisible();
  await expect(banner).toContainText("MCMA • ZONE-A");
  await expect(banner.getByRole("link", { name: "Ouvrir le run" }).first()).toHaveAttribute(
    "href",
    new RegExp(`/accounts/${MCMA_A}/agent/runs/`),
  );
});

test("READY_FOR_HUMAN_REVIEW offers no confirmation and no portal control", async ({ page }) => {
  await page.goto(`/accounts/${MCMA_A}/agent/runs/${READY_JOB}`);

  await expect(
    page.getByText(
      "Aucune validation finale ni clôture n'a été effectuée automatiquement. Vérifiez les saisies dans SinAuto avant de poursuivre manuellement.",
    ),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "Confirmer la vérification" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Signaler un problème" })).toBeVisible();

  for (const forbidden of ["Valider", "Clôturer", "Enregistrer SinAuto", "Finaliser", "GED"]) {
    await expect(page.getByRole("button", { name: new RegExp(forbidden) })).toHaveCount(0);
  }
});

test("AWAITING_HUMAN_CONFIRMATION offers the two application actions", async ({ page }) => {
  await page.goto(`/accounts/${MCMA_A}/agent/runs/${AWAITING_JOB}`);

  await expect(page.getByRole("heading", { name: "Confirmation requise" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Confirmer la vérification" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Signaler un problème" })).toBeVisible();
  // Not the READY instructions: that window is already closed.
  await expect(page.getByText("Fermez la fenêtre SinAuto lorsque vous avez terminé.")).toHaveCount(0);
});

test("the security headers are served with every index response", async ({ request }) => {
  for (const address of ["/", `/accounts/${MCMA_A}/agent/runs/${READY_JOB}`]) {
    const response = await request.get(address);
    expect(response.status()).toBe(200);
    const csp = response.headers()["content-security-policy"];
    expect(csp).toContain("default-src 'self'");
    expect(csp).toContain("frame-ancestors 'none'");
    expect(csp).not.toContain("unsafe-inline");
    expect(csp).not.toContain("unsafe-eval");
    expect(response.headers()["x-frame-options"]).toBe("DENY");
  }
});

test("the SPA fallback does not swallow API routes", async ({ request }) => {
  const accounts = await request.get("/accounts");
  expect(accounts.status()).toBe(200);
  expect(accounts.headers()["content-type"]).toContain("application/json");

  // A mistyped API path stays a backend 404 rather than becoming HTML 200.
  const typo = await request.get("/jobs/typo");
  expect(typo.status()).toBe(404);
  expect(typo.headers()["content-type"]).not.toContain("text/html");
});

test("the browser can open a native SSE connection to /events", async ({ page }) => {
  // A real EventSource, in a real browser, against the served origin. This
  // is the only way to prove four things at once: /events was not swallowed
  // by the SPA fallback (an EventSource handed index.html fails), the route
  // is functional, connect-src 'self' permits the connection, and the
  // credentials travel same-origin.
  //
  // Only the "open" event is observed. Nothing here reads a payload or
  // derives job state from the stream — that stays the authoritative GET's
  // job, exactly as in the application itself.
  await page.goto("/overview");

  const opened = await page.evaluate(async () => {
    return await new Promise<string>((resolve) => {
      const source = new EventSource("/events", { withCredentials: true });
      const finish = (outcome: string) => {
        source.close();
        resolve(outcome);
      };
      const timer = setTimeout(() => finish("timeout"), 10_000);
      source.addEventListener("open", () => {
        clearTimeout(timer);
        finish("open");
      });
      source.addEventListener("error", () => {
        clearTimeout(timer);
        finish("error");
      });
    });
  });

  expect(opened).toBe("open");
});

test("the SPA fallback does not answer /events with the index document", async ({ page }) => {
  // The complementary half: a frontend route still returns HTML, so the
  // check above is about /events specifically and not about a server that
  // returns nothing anywhere.
  const index = await page.request.get("/overview");
  expect(index.headers()["content-type"]).toContain("text/html");

  const events = await page.request.get("/events", { timeout: 5000 }).catch(() => null);
  if (events !== null) {
    expect(events.headers()["content-type"] ?? "").not.toContain("text/html");
  }
});

test("no source map is reachable from the served origin", async ({ request, page }) => {
  await page.goto("/overview");
  const scriptSrc = await page.getAttribute("script[src]", "src");
  expect(scriptSrc).not.toBeNull();
  const map = await request.get(`${scriptSrc}.map`);
  expect(map.status()).toBe(404);
});
