import { describe, expect, it } from "vitest";
import { screen } from "@testing-library/react";
import { AccountRail } from "./AccountRail";
import { renderWithRouter } from "../../test/renderApp";
import { READ_ONLY_ACCOUNT, TEST_ACCOUNTS, WRITABLE_ACCOUNT } from "../../test/fixtures";

describe("AccountRail", () => {
  it("announces a loading state without inventing accounts", () => {
    renderWithRouter(<AccountRail state="loading" accounts={[]} activeAccountId={null} />);
    expect(screen.getByText("Chargement des comptes portail")).toBeInTheDocument();
    expect(screen.queryAllByRole("link")).toHaveLength(0);
  });

  it("says plainly when no account is attributed", () => {
    renderWithRouter(<AccountRail state="empty" accounts={[]} activeAccountId={null} />);
    expect(screen.getByText("Aucun compte portail ne vous est attribué.")).toBeInTheDocument();
  });

  it("reports an unavailable account list", () => {
    renderWithRouter(<AccountRail state="error" accounts={[]} activeAccountId={null} />);
    expect(screen.getByText(/Liste des comptes indisponible/)).toBeInTheDocument();
  });

  it("names each account by entity and scope", () => {
    renderWithRouter(
      <AccountRail state="ready" accounts={TEST_ACCOUNTS} activeAccountId={null} />,
    );
    expect(screen.getByText("MCMA • ZONE-A")).toBeInTheDocument();
    expect(screen.getByText("MAMDA • ZONE-B")).toBeInTheDocument();
  });

  it("marks a non-writable account as read only", () => {
    renderWithRouter(
      <AccountRail state="ready" accounts={[READ_ONLY_ACCOUNT]} activeAccountId={null} />,
    );
    expect(screen.getByText("Lecture seule")).toBeInTheDocument();
  });

  it("offers no agent entry for a read-only account", () => {
    renderWithRouter(
      <AccountRail
        state="ready"
        accounts={[READ_ONLY_ACCOUNT]}
        activeAccountId={READ_ONLY_ACCOUNT.accountId}
      />,
    );
    expect(screen.getByRole("link", { name: "File de travail" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Agent dossier" })).toBeNull();
  });

  it("offers the agent entry for the open writable account", () => {
    renderWithRouter(
      <AccountRail
        state="ready"
        accounts={[WRITABLE_ACCOUNT]}
        activeAccountId={WRITABLE_ACCOUNT.accountId}
      />,
    );
    expect(screen.getByRole("link", { name: "Agent dossier" })).toBeInTheDocument();
  });

  it("expands the navigation of the open account only", () => {
    renderWithRouter(
      <AccountRail
        state="ready"
        accounts={TEST_ACCOUNTS}
        activeAccountId={WRITABLE_ACCOUNT.accountId}
      />,
    );
    // Exactly one account carries sub-navigation, so a work-queue link can
    // never be read as belonging to the other account.
    expect(screen.getAllByRole("link", { name: "File de travail" })).toHaveLength(1);
    expect(screen.getAllByRole("link", { name: "Agent dossier" })).toHaveLength(1);
  });

  it("names only the open sub-page as the current page", () => {
    const { container } = renderWithRouter(
      <AccountRail
        state="ready"
        accounts={[WRITABLE_ACCOUNT]}
        activeAccountId={WRITABLE_ACCOUNT.accountId}
      />,
      `/accounts/${WRITABLE_ACCOUNT.accountId}/agent`,
    );
    // The account header link opens the work queue, which is NOT the page
    // being viewed here, so it must not claim aria-current="page".
    const current = container.querySelectorAll('[aria-current="page"]');
    expect(current).toHaveLength(1);
    expect(current[0]).toHaveTextContent("Agent dossier");
  });

  it("marks the open account as the current item in the list", () => {
    const { container } = renderWithRouter(
      <AccountRail
        state="ready"
        accounts={TEST_ACCOUNTS}
        activeAccountId={WRITABLE_ACCOUNT.accountId}
      />,
      `/accounts/${WRITABLE_ACCOUNT.accountId}/agent`,
    );
    const currentItems = container.querySelectorAll('li[aria-current="true"]');
    expect(currentItems).toHaveLength(1);
    expect(currentItems[0]).toHaveTextContent("MCMA • ZONE-A");
  });

  it("renders account labels as text", () => {
    // Portal-supplied strings are values, never markup.
    const hostile = {
      ...WRITABLE_ACCOUNT,
      label: "<img src=x onerror=alert(1)>",
    };
    const { container } = renderWithRouter(
      <AccountRail state="ready" accounts={[hostile]} activeAccountId={null} />,
    );
    expect(screen.getByText("<img src=x onerror=alert(1)>")).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
  });
});
