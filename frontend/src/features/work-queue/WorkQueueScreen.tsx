import type { PortalAccount } from "@shared/types";
import { AccountWorkspaceHeader } from "@features/accounts/AccountWorkspaceHeader";
import { EmptyState, Panel } from "@shared/ui";

interface WorkQueueScreenProps {
  /** Resolved by the account route guard before this screen mounts. */
  readonly account: PortalAccount;
}

/**
 * The claims an employee works through for one portal account.
 *
 * Reachable for every account the employee can see, including read-only
 * ones. The claim list itself is not implemented yet.
 */
export function WorkQueueScreen({ account }: WorkQueueScreenProps) {
  return (
    <div className="u-stack-5">
      <AccountWorkspaceHeader title="File de travail" resolution={{ status: "resolved", account }} />

      <Panel
        title="Sinistres"
        description="Recherche, filtres et suivi employé arriveront à l'étape suivante."
      >
        <EmptyState title="File non chargée">
          Les sinistres de ce compte s'afficheront ici une fois la liste reliée au serveur.
        </EmptyState>
      </Panel>
    </div>
  );
}
