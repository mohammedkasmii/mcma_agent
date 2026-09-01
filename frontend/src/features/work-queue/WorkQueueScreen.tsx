import { AccountWorkspaceHeader } from "@features/accounts/AccountWorkspaceHeader";
import { EmptyState, Panel } from "@shared/ui";

/**
 * The claims an employee works through for one portal account.
 *
 * STEP 1 renders the frame only. The account is unresolved because the
 * account list is not connected yet, so the header says so instead of
 * showing an identifier. No claim row, status control or note field exists
 * here yet.
 */
export function WorkQueueScreen() {
  return (
    <div className="u-stack-5">
      <AccountWorkspaceHeader title="File de travail" account={null} />

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
