import { beforeEach, describe, expect, it } from "vitest";
import { screen } from "@testing-library/react";
import { renderAppAt } from "../test/renderApp";
import { mockAccounts } from "../test/apiMock";

// Routing is what these cases are about, so the account list is stubbed to a
// benign empty response rather than left to hit a real network.
beforeEach(() => {
  mockAccounts([]);
});

describe("application routing", () => {
  it("sends the root address to the overview screen", () => {
    renderAppAt("/");
    expect(screen.getByRole("heading", { name: "Vue d'ensemble" })).toBeInTheDocument();
  });

  it("renders the overview screen", () => {
    renderAppAt("/overview");
    expect(screen.getByRole("heading", { name: "Vue d'ensemble" })).toBeInTheDocument();
  });

  it("renders the work queue for an account address", () => {
    renderAppAt("/accounts/test-account-writable/work");
    expect(screen.getByRole("heading", { name: "File de travail" })).toBeInTheDocument();
  });

  it("renders the agent screen for an account address", () => {
    renderAppAt("/accounts/test-account-writable/agent");
    expect(screen.getByRole("heading", { name: "Agent dossier" })).toBeInTheDocument();
  });

  it("shows a dead-end screen for an unknown address", () => {
    renderAppAt("/nowhere");
    expect(screen.getByRole("heading", { name: "Page introuvable" })).toBeInTheDocument();
  });
});

describe("application shell", () => {
  it("keeps the account rail present on every screen", () => {
    renderAppAt("/overview");
    expect(screen.getByRole("navigation", { name: "Comptes portail" })).toBeInTheDocument();
  });

  it("keeps the account rail present on an account screen", () => {
    renderAppAt("/accounts/test-account-writable/work");
    expect(screen.getByRole("navigation", { name: "Comptes portail" })).toBeInTheDocument();
  });

  it("renders no account record while the account list is unresolved", () => {
    // STEP 1 fetches nothing, so the rail must show a structural placeholder
    // and never a fabricated account.
    renderAppAt("/overview");
    const rail = screen.getByRole("navigation", { name: "Comptes portail" });
    expect(rail.querySelector("[aria-busy='true']")).not.toBeNull();
    expect(screen.queryByRole("link", { name: /Compte de test/ })).toBeNull();
  });

  it("does not display the account identifier from the address", () => {
    // Internal identifiers are not employee-facing copy.
    renderAppAt("/accounts/test-account-writable/work");
    expect(screen.queryByText(/test-account-writable/)).toBeNull();
  });
});
