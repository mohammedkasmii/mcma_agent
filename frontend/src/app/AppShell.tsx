import { Link, Outlet, useMatch } from "react-router-dom";
import { AccountRail } from "@features/accounts/AccountRail";
import { useAccountRail } from "@features/accounts/useAccountRail";
import { ROUTES } from "@shared/utils/routes";
import styles from "./AppShell.module.css";

/**
 * The frame every screen renders inside.
 *
 * The account rail is part of the shell rather than part of a screen, so
 * the set of portal accounts and the one currently open stay on screen
 * through every navigation — including while an automation is running.
 *
 * The active account is derived from the URL, never from component state:
 * a reload or a pasted link restores the same account context.
 */
export function AppShell() {
  const { state, accounts } = useAccountRail();
  const accountMatch = useMatch("/accounts/:accountId/*");
  const activeAccountId = accountMatch?.params.accountId ?? null;

  return (
    <div className={styles.shell}>
      <a className={styles.skipLink} href="#main">
        Aller au contenu
      </a>
      <header className={styles.topbar}>
        <Link to={ROUTES.overview} className={styles.brand}>
          MCMA Operations
        </Link>
        <p className={styles.environment}>Poste local</p>
      </header>
      <AccountRail state={state} accounts={accounts} activeAccountId={activeAccountId} />
      <main className={styles.content} id="main">
        <div className={styles.contentInner}>
          <Outlet />
        </div>
      </main>
    </div>
  );
}
