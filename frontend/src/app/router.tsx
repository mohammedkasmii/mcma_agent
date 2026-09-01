import type { RouteObject } from "react-router-dom";
import { createBrowserRouter, Navigate } from "react-router-dom";
import { AppShell } from "./AppShell";
import { OverviewScreen } from "@features/overview/OverviewScreen";
import { WorkQueueScreen } from "@features/work-queue/WorkQueueScreen";
import { AgentScreen } from "@features/agent/AgentScreen";
import { NotFoundScreen } from "./NotFoundScreen";
import { AccountRoute } from "@features/accounts/AccountRoute";
import { ROUTES } from "@shared/utils/routes";

/**
 * The route table, exported separately from the router instance so tests
 * can mount the same routes in a memory router without a second definition
 * of the application's structure.
 *
 * Account-scoped screens sit under /accounts/:accountId so the account is
 * part of the address, not of component state.
 */
export const appRoutes: RouteObject[] = [
  {
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
        // requireWritable is the enforcement: a directly typed agent URL for
        // a read-only account never mounts AgentScreen.
        path: ROUTES.accountAgent,
        element: (
          <AccountRoute title="Agent dossier" requireWritable>
            {(account) => <AgentScreen account={account} />}
          </AccountRoute>
        ),
      },
      { path: "*", element: <NotFoundScreen /> },
    ],
  },
];

export function createAppRouter() {
  return createBrowserRouter(appRoutes);
}
