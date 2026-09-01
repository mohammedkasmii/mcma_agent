import { describe, expect, it } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { renderAppAt } from "../../test/renderApp";
import { mockAccounts, mockApiError, mockNetworkFailure } from "../../test/apiMock";
import {
  READ_ONLY_ACCOUNT_WIRE,
  TEST_ACCOUNTS_WIRE,
  UNKNOWN_ACCOUNT_ID,
  WRITABLE_ACCOUNT_WIRE,
} from "../../test/fixtures";

const WORK = (id: string) => `/accounts/${id}/work`;
const AGENT = (id: string) => `/accounts/${id}/agent`;

describe("account rail against the real query", () => {
  it("shows the loading state before the response arrives", () => {
    mockAccounts(TEST_ACCOUNTS_WIRE);
    renderAppAt("/overview");
    expect(screen.getByText("Chargement des comptes portail")).toBeInTheDocument();
  });

  it("renders the accounts the backend returned", async () => {
    mockAccounts(TEST_ACCOUNTS_WIRE);
    renderAppAt("/overview");

    expect(await screen.findByText("MCMA • ZONE-A")).toBeInTheDocument();
    expect(screen.getByText("MAMDA • ZONE-B")).toBeInTheDocument();
    expect(screen.getByText("Compte de test A")).toBeInTheDocument();
    // Two accounts are connected in the fixture set.
    expect(screen.getAllByText("Connecté").length).toBeGreaterThan(0);
    expect(screen.getByText("Reconnexion requise")).toBeInTheDocument();
    expect(screen.getByText("Lecture seule")).toBeInTheDocument();
  });

  it("says plainly when the employee has no accounts", async () => {
    mockAccounts([]);
    renderAppAt("/overview");
    expect(
      await screen.findByText("Aucun compte portail ne vous est attribué."),
    ).toBeInTheDocument();
  });

  it("reports an unreachable server rather than an empty list", async () => {
    mockNetworkFailure();
    renderAppAt("/overview");
    expect(await screen.findByText(/Liste des comptes indisponible/)).toBeInTheDocument();
  });

  it("reports a backend error rather than an empty list", async () => {
    mockApiError(401, "UNAUTHENTICATED", "authentication required");
    renderAppAt("/overview");
    expect(await screen.findByText(/Liste des comptes indisponible/)).toBeInTheDocument();
  });
});

describe("account route resolution", () => {
  it("shows the resolved account identity in the work queue header", async () => {
    mockAccounts(TEST_ACCOUNTS_WIRE);
    renderAppAt(WORK(WRITABLE_ACCOUNT_WIRE.account_id));

    expect(await screen.findByRole("heading", { name: "Sinistres" })).toBeInTheDocument();
    // The header identity, not only the rail entry.
    await waitFor(() => expect(screen.getAllByText("MCMA • ZONE-A").length).toBeGreaterThan(1));
    expect(screen.queryByText("Compte en cours de chargement")).toBeNull();
  });

  it("never falls back to the account id from the URL as identity", async () => {
    mockAccounts(TEST_ACCOUNTS_WIRE);
    renderAppAt(WORK(WRITABLE_ACCOUNT_WIRE.account_id));

    await screen.findByRole("heading", { name: "Sinistres" });
    expect(screen.queryByText(/test-account-writable/)).toBeNull();
  });

  it("fails closed for an account id that is not in the list", async () => {
    mockAccounts(TEST_ACCOUNTS_WIRE);
    renderAppAt(WORK(UNKNOWN_ACCOUNT_ID));

    expect(await screen.findByText("Ce compte n'est pas disponible")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Sinistres" })).toBeNull();
    expect(screen.queryByText(new RegExp(UNKNOWN_ACCOUNT_ID))).toBeNull();
  });

  it("does not pretend an account exists while the list is failing", async () => {
    mockNetworkFailure();
    renderAppAt(WORK(WRITABLE_ACCOUNT_WIRE.account_id));

    expect(await screen.findByText("Impossible de charger vos comptes")).toBeInTheDocument();
    expect(screen.queryByText("MCMA • ZONE-A")).toBeNull();
  });

  it("does not render the raw server message on an API failure", async () => {
    mockApiError(401, "UNAUTHENTICATED", "authentication required");
    renderAppAt(WORK(WRITABLE_ACCOUNT_WIRE.account_id));

    expect(await screen.findByText("Impossible de charger vos comptes")).toBeInTheDocument();
    expect(screen.getByText("Votre session a expiré. Reconnectez-vous.")).toBeInTheDocument();
    expect(screen.queryByText(/authentication required/)).toBeNull();
  });
});

describe("agent route capability", () => {
  it("renders the agent screen for an account the backend marks writable", async () => {
    mockAccounts(TEST_ACCOUNTS_WIRE);
    renderAppAt(AGENT(WRITABLE_ACCOUNT_WIRE.account_id));

    // The screen title also renders while the account is still resolving, so
    // the panel heading is what proves AgentScreen actually mounted. It is
    // the New Run panel since MACRO STEP 4.
    expect(await screen.findByRole("heading", { name: "Nouveau run" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Agent dossier" })).toBeInTheDocument();
  });

  it("refuses a directly typed agent URL for a read-only account", async () => {
    mockAccounts(TEST_ACCOUNTS_WIRE);
    renderAppAt(AGENT(READ_ONLY_ACCOUNT_WIRE.account_id));

    expect(await screen.findByText("Ce compte est en lecture seule")).toBeInTheDocument();
    // The automation surface itself never mounts.
    expect(screen.queryByRole("heading", { name: "Nouveau run" })).toBeNull();
    expect(screen.queryByText(/Ce que l'agent ne fera pas/)).toBeNull();
  });

  it("refuses an agent URL for an unknown account", async () => {
    mockAccounts(TEST_ACCOUNTS_WIRE);
    renderAppAt(AGENT(UNKNOWN_ACCOUNT_ID));

    expect(await screen.findByText("Ce compte n'est pas disponible")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Nouveau run" })).toBeNull();
  });

  it("refuses an agent URL while the account list is failing", async () => {
    mockNetworkFailure();
    renderAppAt(AGENT(WRITABLE_ACCOUNT_WIRE.account_id));

    expect(await screen.findByText("Impossible de charger vos comptes")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Nouveau run" })).toBeNull();
  });

  it("keeps the work queue reachable for a read-only account", async () => {
    mockAccounts(TEST_ACCOUNTS_WIRE);
    renderAppAt(WORK(READ_ONLY_ACCOUNT_WIRE.account_id));

    expect(await screen.findByRole("heading", { name: "Sinistres" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "File de travail" })).toBeInTheDocument();
    expect(screen.getAllByText("Lecture seule").length).toBeGreaterThan(0);
  });

  it("offers no agent navigation for a read-only account", async () => {
    mockAccounts(TEST_ACCOUNTS_WIRE);
    renderAppAt(WORK(READ_ONLY_ACCOUNT_WIRE.account_id));

    await screen.findByRole("heading", { name: "Sinistres" });
    expect(screen.queryByRole("link", { name: "Agent dossier" })).toBeNull();
  });
});
