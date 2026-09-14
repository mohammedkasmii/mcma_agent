import { useMemo } from "react";
import { Link } from "react-router-dom";
import type { PortalAccount } from "@shared/types";
import { EmptyState, Panel, Skeleton, StatusBadge } from "@shared/ui";
import {
  capabilityLabel,
  connectionLabel,
  connectionTone,
  formatAccountIdentity,
} from "@shared/utils/accountIdentity";
import {
  activeNotificationsLabel,
  concernedDossiersLabel,
  newNotificationsLabel,
} from "@shared/utils/notificationWording";
import { accountWorkPath } from "@shared/utils/routes";
import { NotificationFreshness } from "@features/accounts/NotificationFreshness";
import { toApiError, useAccountsQuery } from "@features/accounts/queries";
import styles from "./OverviewScreen.module.css";

/**
 * The entry screen: which portal account needs attention, and how current
 * that answer is.
 *
 * Every number comes from GET /accounts, which derives them server-side from
 * the same category_presence rows the work queue reads. This screen fetches
 * no claims and counts nothing itself — a second count is a second truth.
 *
 * Two numbers are shown side by side throughout, because they answer
 * different questions: notifications are category memberships (what the
 * portal's own bar counts) and dossiers are files to open.
 */
export function OverviewScreen() {
  const query = useAccountsQuery();
  const accounts = useMemo(() => query.data ?? [], [query.data]);

  const totals = useMemo(
    () => ({
      // Summing per-account distinct counts is itself distinct: a claim
      // belongs to exactly one account, so no dossier can be counted twice
      // and two accounts' identical portal ids are two different dossiers.
      unreadNotifications: accounts.reduce((sum, account) => sum + account.unreadNotificationCount, 0),
      unreadDossiers: accounts.reduce((sum, account) => sum + account.unreadClaimCount, 0),
      active: accounts.reduce((sum, account) => sum + account.activeNotificationCount, 0),
    }),
    [accounts],
  );

  const ready = query.isSuccess && accounts.length > 0;

  return (
    <div className="u-stack-5">
      <header>
        <h1 className="t-screen-title">Vue d'ensemble</h1>
        <p className="t-secondary">
          Les notifications arrivées sur vos comptes portail et l'état de leur dernière
          actualisation.
        </p>
      </header>

      <Panel
        title="Nouvelles notifications"
        description="Tous comptes confondus, parmi ceux auxquels vous avez accès."
      >
        {query.isPending ? <LoadingLines label="Chargement des totaux" rows={2} /> : null}

        {query.isError ? (
          <EmptyState title="Impossible de charger vos comptes">
            {toApiError(query.error).message}
          </EmptyState>
        ) : null}

        {query.isSuccess && accounts.length === 0 ? (
          <EmptyState title="Aucun compte portail ne vous est attribué">
            Demandez l'accès à un compte pour voir ses notifications.
          </EmptyState>
        ) : null}

        {ready ? (
          <div className={styles.totals}>
            <p className={styles.totalHeadline}>
              {`${newNotificationsLabel(totals.unreadNotifications)} au total`}
            </p>
            <p className={styles.totalSecondary}>
              {`${concernedDossiersLabel(totals.unreadDossiers)} au total`}
            </p>
            <p className="t-meta">
              {`${activeNotificationsLabel(totals.active)} suivies actuellement sur le portail.`}
            </p>
          </div>
        ) : null}
      </Panel>

      <Panel title="Comptes portail" description="État et volume de travail par compte.">
        {query.isPending ? <LoadingLines label="Chargement du résumé par compte" rows={3} /> : null}

        {ready ? (
          <ul className={styles.accounts}>
            {accounts.map((account) => (
              <AccountSummary account={account} key={account.accountId} />
            ))}
          </ul>
        ) : null}
      </Panel>
    </div>
  );
}

function AccountSummary({ account }: { readonly account: PortalAccount }) {
  const identity = formatAccountIdentity(account);
  const unread = account.unreadNotificationCount;

  return (
    <li className={styles.account}>
      <div className={styles.head}>
        <span className={styles.identity}>{identity}</span>
        <StatusBadge tone={connectionTone(account.connectionState)}>
          {connectionLabel(account.connectionState)}
        </StatusBadge>
        <StatusBadge tone={account.writable ? "connected" : "readonly"}>
          {capabilityLabel(account)}
        </StatusBadge>
      </div>

      <p className={styles.label}>{account.label}</p>

      {unread > 0 ? (
        <p className={styles.counts}>
          <span className={styles.new}>{newNotificationsLabel(unread)}</span>
          <span className={styles.dossiers}>{concernedDossiersLabel(account.unreadClaimCount)}</span>
        </p>
      ) : (
        <p className={styles.nothingNew}>Aucune nouvelle notification</p>
      )}

      <p className="t-meta">{activeNotificationsLabel(account.activeNotificationCount)}</p>

      <NotificationFreshness account={account} />

      <p>
        {/* The visible words are the same on every card, so the account is
            added to the accessible name -- otherwise a screen-reader list of
            links reads as four identical entries. */}
        <Link
          aria-label={`Ouvrir la file de travail — ${identity}`}
          className={styles.open}
          to={accountWorkPath(account.accountId)}
        >
          Ouvrir la file de travail
        </Link>
      </p>
    </li>
  );
}

function LoadingLines({ label, rows }: { readonly label: string; readonly rows: number }) {
  return (
    <div className={styles.loading} aria-busy="true">
      {/* Distinct per panel: two identical hidden labels would read as one
          ambiguous "loading" to a screen reader, and to a test. */}
      <p className="u-visually-hidden">{label}</p>
      {Array.from({ length: rows }, (_unused, slot) => (
        <Skeleton key={slot} size="lg" />
      ))}
    </div>
  );
}
