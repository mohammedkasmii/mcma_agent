import type { RouteObject } from "react-router-dom";
import { createBrowserRouter, Navigate } from "react-router-dom";
import { AppShell } from "./AppShell";
import { OverviewScreen } from "@features/overview/OverviewScreen";
import { WorkQueueScreen } from "@features/work-queue/WorkQueueScreen";
import { AgentScreen } from "@features/agent/AgentScreen";
import { NotFoundScreen } from "./NotFoundScreen";
import { AccountRoute } from "@features/accounts/AccountRoute";
import { ClaimDetailScreen } from "@features/claims/ClaimDetailScreen";
import { AgentRunScreen } from "@features/agent/AgentRunScreen";
import { LoginScreen } from "@features/auth/LoginScreen";
import { RequireAdmin, RequireAuth } from "@features/auth/RequireAuth";
import { AdminUsersScreen } from "@features/admin/AdminUsersScreen";
import { ROUTES } from "@shared/utils/routes";

/**
 * The route table, exported separately from the router instance so tests
 * can mount the same routes in a memory router without a second definition
 * of the application's structure.
 *
 * Account-scoped screens sit under /accounts/:accountId so the account is
 * part of the address, not of component state.
 */
const shellRoute: RouteObject = {
    element: <AppShell />,
    children: [
      { index: true, element: <Navigate to={ROUTES.overview} replace /> },
      { path: ROUTES.overview, element: <OverviewScreen /> },
      {
        path: ROUTES.accountWork,
        element: (
          <AccountRoute title="File de travail">
            {(account) => <WorkQueueScreen account={account} />}
          </AccountRoute>
        ),
      },
      {
        path: ROUTES.accountClaim,
        element: (
          <AccountRoute title="Dossier">
            {(account) => <ClaimDetailScreen account={account} />}
          </AccountRoute>
        ),
      },
      {
        // requireWritable is the enforcement: a directly typed agent URL for
        // a read-only account never mounts AgentScreen.
        path: ROUTES.accountAgent,
        element: (
          <AccountRoute title="Agent dossier" requireWritable>
            {/* Keyed by the account: a dossier is chosen for one explicit
                account, so switching account requires choosing again rather
                than leaving the previous file armed for submission. */}
            {(account) => <AgentScreen key={account.accountId} account={account} />}
          </AccountRoute>
        ),
      },
      {
        // The run screen sits behind the same writable gate: a read-only
        // account has no runs, and a typed URL must not suggest otherwise.
        path: ROUTES.accountAgentJob,
        element: (
          <AccountRoute title="Agent dossier" requireWritable>
            {(account) => <AgentRunScreen account={account} />}
          </AccountRoute>
        ),
      },
      {
        path: ROUTES.adminUsers,
        element: (
          <RequireAdmin>
            <AdminUsersScreen />
          </RequireAdmin>
        ),
      },
      { path: "*", element: <NotFoundScreen /> },
    ],
  };

/**
 * The login screen sits outside the auth gate; everything else (shell,
 * account queries, event stream) is a child of RequireAuth and therefore
 * mounts only after /auth/me confirmed a session.
 */
export const appRoutes: RouteObject[] = [
  { path: ROUTES.login, element: <LoginScreen /> },
  { element: <RequireAuth />, children: [shellRoute] },
];

export function createAppRouter() {
  return createBrowserRouter(appRoutes);
}
