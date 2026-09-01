import { StatusBadge } from "@shared/ui";
import { capabilityLabel, formatAccountIdentity } from "@shared/utils/accountIdentity";
import type { AccountResolution } from "./queries";
import styles from "./AccountWorkspaceHeader.module.css";

interface AccountWorkspaceHeaderProps {
  readonly title: string;
  readonly resolution: AccountResolution;
}

/**
 * Names the screen and, above it, the account the screen belongs to.
 *
 * The identity line sits above the title on purpose: an employee should read
 * which portal account they are in before reading what they are doing in it.
 *
 * Every unresolved case says what is actually true. The opaque account id
 * from the URL is never used as a stand-in identity: it is not a name, and
 * showing it would suggest the account was found when it was not.
 */
export function AccountWorkspaceHeader({ title, resolution }: AccountWorkspaceHeaderProps) {
  return (
    <header className={styles.header}>
      <div className={styles.identityRow}>
        {resolution.status === "resolved" ? (
          <>
            <span className={styles.identity}>{formatAccountIdentity(resolution.account)}</span>
            <StatusBadge tone={resolution.account.writable ? "connected" : "readonly"}>
              {capabilityLabel(resolution.account)}
            </StatusBadge>
          </>
        ) : null}
        {resolution.status === "loading" ? (
          <span className={styles.identityPending}>Compte en cours de chargement</span>
        ) : null}
        {resolution.status === "unknown" ? (
          <span className={styles.identityPending}>Compte indisponible</span>
        ) : null}
        {resolution.status === "error" ? (
          <span className={styles.identityPending}>Compte non vérifiable</span>
        ) : null}
      </div>
      <h1 className="t-screen-title">{title}</h1>
    </header>
  );
}
