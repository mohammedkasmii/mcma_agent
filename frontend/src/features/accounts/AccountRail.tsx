import { Link, NavLink } from "react-router-dom";
import { Skeleton, StatusBadge } from "@shared/ui";
import type { AccountsLoadState, PortalAccount } from "@shared/types";
import {
  capabilityLabel,
  connectionLabel,
  connectionMarker,
  formatAccountIdentity,
} from "@shared/utils/accountIdentity";
import { accountAgentPath, accountWorkPath } from "@shared/utils/routes";
import { cx } from "@shared/utils/classNames";
import styles from "./AccountRail.module.css";

interface AccountRailProps {
  readonly state: AccountsLoadState;
  readonly accounts: readonly PortalAccount[];
  /** Account currently open, derived from the URL. */
  readonly activeAccountId: string | null;
}

/**
 * The rail is the spine of the workspace: it is always present, and the
 * account an employee is working in is always visible in it.
 *
 * Two rules are structural rather than cosmetic:
 *  - the agent entry appears only for accounts the backend marks writable,
 *    so a read-only MAMDA account never offers an automation action,
 *  - work-queue and agent links belong to a single account item, so a link
 *    can never be read as belonging to the account above or below it.
 */
export function AccountRail({ state, accounts, activeAccountId }: AccountRailProps) {
  return (
    <nav className={styles.rail} aria-label="Comptes portail">
      <p className={styles.railTitle}>Comptes portail</p>
      {state === "loading" ? <RailLoading /> : null}
      {state === "empty" ? (
        <p className={styles.notice}>Aucun compte portail ne vous est attribué.</p>
      ) : null}
      {state === "error" ? (
        <p className={styles.notice}>Liste des comptes indisponible. Actualisez la page.</p>
      ) : null}
      {state === "ready" ? (
        <ul className={styles.list}>
          {accounts.map((account) => (
            <AccountItem
              key={account.accountId}
              account={account}
              isActive={account.accountId === activeAccountId}
            />
          ))}
        </ul>
      ) : null}
    </nav>
  );
}

function RailLoading() {
  return (
    <div className={styles.loading} aria-busy="true">
      <p className="u-visually-hidden">Chargement des comptes portail</p>
      {[0, 1, 2].map((slot) => (
        <div className={styles.loadingItem} key={slot}>
          <Skeleton size="lg" />
          <Skeleton size="sm" />
        </div>
      ))}
    </div>
  );
}

interface AccountItemProps {
  readonly account: PortalAccount;
  readonly isActive: boolean;
}

function AccountItem({ account, isActive }: AccountItemProps) {
  const marker = connectionMarker(account.connectionState);
  const identity = formatAccountIdentity(account);

  return (
    // aria-current="true" on the container marks the open account as the
    // current item in the account list. The header link below is a plain
    // Link, not a NavLink: it opens the work queue, so marking it "page"
    // would be false whenever the agent screen is the one actually open.
    <li className={cx(styles.item, isActive && styles.itemActive)} aria-current={isActive ? "true" : undefined}>
      <Link to={accountWorkPath(account.accountId)} className={cx(styles.itemLink)}>
        <span className={styles.identity}>{identity}</span>
        <span className={styles.label}>{account.label}</span>
        <span className={styles.state}>
          <span className={cx(styles.marker, styles[marker])} aria-hidden="true" />
          {connectionLabel(account.connectionState)}
        </span>
      </Link>
      <p className={styles.capability}>
        <StatusBadge tone={account.writable ? "connected" : "readonly"}>
          {capabilityLabel(account)}
        </StatusBadge>
      </p>
      {isActive ? (
        <ul className={styles.subNav}>
          <li>
            <NavLink to={accountWorkPath(account.accountId)} className={cx(styles.subLink)}>
              File de travail
            </NavLink>
          </li>
          {account.writable ? (
            <li>
              <NavLink to={accountAgentPath(account.accountId)} className={cx(styles.subLink)}>
                Agent dossier
              </NavLink>
            </li>
          ) : null}
        </ul>
      ) : null}
    </li>
  );
}
