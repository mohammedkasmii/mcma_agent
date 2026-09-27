import { Link, NavLink, Outlet, useMatch } from "react-router-dom";
import { AccountRail } from "@features/accounts/AccountRail";
import { useAccountRail } from "@features/accounts/useAccountRail";
import { ActiveRunBanner } from "@features/jobs/ActiveRunBanner";
import { useEventStream } from "@shared/events/useEventStream";
import { useAuth } from "@features/auth/AuthProvider";
import { cx } from "@shared/utils/classNames";
import { Button } from "@shared/ui";
import { roleLabel } from "@shared/utils/roles";
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
 *
 * The active-run banner sits above the routed content rather than inside a
 * screen, because a run needing attention on one account must stay visible
 * while the employee works in another.
 */
export function AppShell() {
  // One connection for the whole application: the shell outlives every
  // navigation, so no screen can open a second stream.
  const auth = useAuth();
  useEventStream(undefined, auth.recheckSession);
  const { state, accounts } = useAccountRail();
  const accountMatch = useMatch("/accounts/:accountId/*");
  const activeAccountId = accountMatch?.params.accountId ?? null;
  const logout = auth.logout;
  const session = auth.state.status === "authenticated" ? auth.state.session : null;

  return (
    <div className={styles.shell}>
      <a className={styles.skipLink} href="#main">
        Aller au contenu
      </a>
      <header className={styles.topbar}>
        <Link to={ROUTES.overview} className={styles.brand}>
          MCMA Operations
        </Link>
        {session?.role === "admin" ? (
          <nav aria-label="Administration">
            <NavLink to={ROUTES.adminUsers} className={cx(styles.navLink)}>
              Utilisateurs
            </NavLink>{" "}
            <NavLink to={ROUTES.adminRunners} className={cx(styles.navLink)}>
              Postes agents
            </NavLink>
          </nav>
        ) : null}
        <div className={styles.userArea}>
          <p className={styles.environment}>
            {session?.localSingleUser ? "Poste local" : "Serveur central"}
          </p>
          {session === null ? null : (
            <>
              <p className={styles.identity}>
                <span>{session.username}</span> <span>{roleLabel(session.role)}</span>
              </p>
              {session.localSingleUser ? null : (
                <Button className={styles.logout} onClick={() => void logout()}>
                  Se déconnecter
                </Button>
              )}
            </>
          )}
        </div>
      </header>
      <AccountRail state={state} accounts={accounts} activeAccountId={activeAccountId} />
      <main className={styles.content} id="main">
        <div className={styles.contentInner}>
          <ActiveRunBanner />
          <Outlet />
        </div>
      </main>
    </div>
  );
}
