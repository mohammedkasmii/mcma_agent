import { describe, expect, it } from "vitest";
import { screen, within } from "@testing-library/react";
import { renderAppAt } from "../../test/renderApp";
import { mockAccounts, mockApiError, mockNetworkFailure } from "../../test/apiMock";
import {
  READ_ONLY_ACCOUNT_WIRE,
  SECOND_WRITABLE_ACCOUNT_WIRE,
  TEST_ACCOUNTS_WIRE,
  WRITABLE_ACCOUNT_WIRE,
} from "../../test/fixtures";

/**
 * The overview answers "which account needs me, and can I trust what it
 * says". Everything it renders comes from GET /accounts; it fetches no
 * claims and counts nothing locally.
 *
 * Assertions are scoped to <main> because the rail names the same accounts
 * on the left of the same screen.
 */

const main = () => within(screen.getByRole("main"));

/** The card for one account, located by the identity it displays. */
async function accountCard(identity: string) {
  const heading = await main().findByText(identity);
  const card = heading.closest("li");
  expect(card).not.toBeNull();
  return within(card as HTMLElement);
}

describe("overview totals across accounts", () => {
  it("adds up new notifications and concerned dossiers over every visible account", async () => {
    // Fixture set: account A has 2 new notifications on 1 dossier, B and C
    // have none. Both numbers are shown, because they answer different
    // questions.
    mockAccounts(TEST_ACCOUNTS_WIRE);
    renderAppAt("/overview");

    expect(await main().findByText("2 nouvelles notifications au total")).toBeInTheDocument();
    expect(main().getByText("1 dossier concerné au total")).toBeInTheDocument();
    // 3 + 1 + 0 active memberships across the three accounts.
    expect(main().getByText(/4 notifications actives suivies actuellement/)).toBeInTheDocument();
  });

  it("never merges two accounts' dossiers into one", async () => {
    // The same portal dossier under two accounts is two dossiers: the total
    // is the sum of per-account distinct counts, never de-duplicated across
    // accounts.
    const first = { ...WRITABLE_ACCOUNT_WIRE, unread_notification_count: 2, unread_claim_count: 1 };
    const second = {
      ...SECOND_WRITABLE_ACCOUNT_WIRE,
      unread_notification_count: 3,
      unread_claim_count: 1,
    };
    mockAccounts([first, second]);
    renderAppAt("/overview");

    expect(await main().findByText("5 nouvelles notifications au total")).toBeInTheDocument();
    expect(main().getByText("2 dossiers concernés au total")).toBeInTheDocument();
  });

  it("uses the singular for a single notification on a single dossier", async () => {
    mockAccounts([{ ...WRITABLE_ACCOUNT_WIRE, unread_notification_count: 1, unread_claim_count: 1 }]);
    renderAppAt("/overview");

    expect(await main().findByText("1 nouvelle notification au total")).toBeInTheDocument();
    expect(main().getByText("1 dossier concerné au total")).toBeInTheDocument();
  });

  it("says zero plainly rather than hiding the panel", async () => {
    mockAccounts([SECOND_WRITABLE_ACCOUNT_WIRE]);
    renderAppAt("/overview");

    expect(await main().findByText("0 nouvelle notification au total")).toBeInTheDocument();
  });
});

describe("overview per account", () => {
  it("shows identity, connection, both counts and the work-queue link", async () => {
    mockAccounts(TEST_ACCOUNTS_WIRE);
    renderAppAt("/overview");

    const card = await accountCard("MCMA • ZONE-A");
    expect(card.getByText("Compte de test A")).toBeInTheDocument();
    expect(card.getByText("Connecté")).toBeInTheDocument();
    expect(card.getByText("2 nouvelles notifications")).toBeInTheDocument();
    expect(card.getByText("1 dossier concerné")).toBeInTheDocument();
    expect(card.getByText("3 notifications actives")).toBeInTheDocument();
    expect(card.getByRole("link", { name: /Ouvrir la file de travail/ })).toHaveAttribute(
      "href",
      `/accounts/${WRITABLE_ACCOUNT_WIRE.account_id}/work`,
    );
  });

  it("names the account in each link, so four links are not read as one", async () => {
    mockAccounts(TEST_ACCOUNTS_WIRE);
    renderAppAt("/overview");

    expect(
      await main().findByRole("link", { name: "Ouvrir la file de travail — MCMA • ZONE-A" }),
    ).toBeInTheDocument();
    expect(
      main().getByRole("link", { name: "Ouvrir la file de travail — MAMDA • ZONE-B" }),
    ).toBeInTheDocument();
  });

  it("says plainly when an account has nothing new", async () => {
    mockAccounts(TEST_ACCOUNTS_WIRE);
    renderAppAt("/overview");

    const card = await accountCard("MAMDA • ZONE-B");
    expect(card.getByText("Aucune nouvelle notification")).toBeInTheDocument();
    expect(card.queryByText(/0 nouvelle notification$/)).toBeNull();
  });

  it("keeps a read-only account visible with its capability stated", async () => {
    mockAccounts(TEST_ACCOUNTS_WIRE);
    renderAppAt("/overview");

    const card = await accountCard("MAMDA • ZONE-B");
    expect(card.getByText("Lecture seule")).toBeInTheDocument();
  });
});

describe("overview refresh confidence", () => {
  it("shows when the account was last refreshed successfully", async () => {
    mockAccounts([WRITABLE_ACCOUNT_WIRE]);
    renderAppAt("/overview");

    const card = await accountCard("MCMA • ZONE-A");
    // Formatted in French local time, never the raw ISO value.
    expect(card.getByText(/^Actualisé le \d{2}\/\d{2}\/\d{4}/)).toBeInTheDocument();
    expect(card.queryByText(/2026-02-01T08:05:00Z/)).toBeNull();
  });

  it("warns that the latest attempt failed while keeping the last success time", async () => {
    mockAccounts([READ_ONLY_ACCOUNT_WIRE]);
    renderAppAt("/overview");

    const card = await accountCard("MAMDA • ZONE-B");
    expect(card.getByText("Dernière tentative échouée")).toBeInTheDocument();
    expect(
      card.getByText(/datent de la dernière actualisation réussie/),
    ).toBeInTheDocument();
    // The older success is still named: the rows on screen do date from it.
    expect(card.getByText(/^Actualisé le 31\/01\/2026/)).toBeInTheDocument();
  });

  it("warns that the latest attempt was incomplete", async () => {
    mockAccounts([
      { ...WRITABLE_ACCOUNT_WIRE, notification_last_attempt_status: "PARTIAL" },
    ]);
    renderAppAt("/overview");

    const card = await accountCard("MCMA • ZONE-A");
    expect(card.getByText("Dernière tentative incomplète")).toBeInTheDocument();
    expect(card.getByText(/Certaines catégories n'ont pas pu être lues/)).toBeInTheDocument();
  });

  it("says an account was never refreshed instead of inventing a time", async () => {
    mockAccounts([SECOND_WRITABLE_ACCOUNT_WIRE]);
    renderAppAt("/overview");

    const card = await accountCard("MCMA • ZONE-C");
    expect(card.getByText("Jamais actualisé avec succès.")).toBeInTheDocument();
    expect(card.queryByText(/Actualisé le/)).toBeNull();
  });

  it("promises no next refresh time", async () => {
    mockAccounts(TEST_ACCOUNTS_WIRE);
    renderAppAt("/overview");

    await main().findByText("2 nouvelles notifications au total");
    // The scheduler exposes no authoritative next-run time, so the screen
    // must not imply one.
    expect(main().queryByText(/prochaine actualisation/i)).toBeNull();
  });
});

describe("overview failure states", () => {
  it("reports an unreachable server rather than zero notifications", async () => {
    mockNetworkFailure();
    renderAppAt("/overview");

    expect(await main().findByText("Impossible de charger vos comptes")).toBeInTheDocument();
    expect(main().queryByText(/nouvelles notifications au total/)).toBeNull();
  });

  it("hides the raw backend message behind an employee-facing one", async () => {
    mockApiError(403, "FORBIDDEN", "account access denied for principal");
    renderAppAt("/overview");

    expect(await main().findByText("Impossible de charger vos comptes")).toBeInTheDocument();
    expect(main().queryByText(/account access denied/)).toBeNull();
  });

  it("says plainly when no account is attributed", async () => {
    mockAccounts([]);
    renderAppAt("/overview");

    expect(
      await main().findByText("Aucun compte portail ne vous est attribué"),
    ).toBeInTheDocument();
  });
});
