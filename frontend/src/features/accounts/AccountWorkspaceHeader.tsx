import { StatusBadge } from "@shared/ui";
import type { PortalAccount } from "@shared/types";
import { capabilityLabel, formatAccountIdentity } from "@shared/utils/accountIdentity";
import styles from "./AccountWorkspaceHeader.module.css";

interface AccountWorkspaceHeaderProps {
  readonly title: string;
  /** Resolved account, or null while the account list is still loading. */
  readonly account: PortalAccount | null;
}

/**
 * Names the screen and, above it, the account the screen belongs to.
 *
 * The identity line sits above the title on purpose: an employee should
 * read which portal account they are in before reading what they are doing
 * in it. While the account is unresolved the line says so rather than
 * falling back to an identifier, which would look like a real account name.
 */
export function AccountWorkspaceHeader({ title, account }: AccountWorkspaceHeaderProps) {
  return (
    <header className={styles.header}>
      <div className={styles.identityRow}>
        {account ? (
          <>
            <span className={styles.identity}>{formatAccountIdentity(account)}</span>
            <StatusBadge tone={account.writable ? "connected" : "readonly"}>
              {capabilityLabel(account)}
            </StatusBadge>
          </>
        ) : (
          <span className={styles.identityPending}>Compte en cours de chargement</span>
        )}
      </div>
      <h1 className="t-screen-title">{title}</h1>
    </header>
  );
}
