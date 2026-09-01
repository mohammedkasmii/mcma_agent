import type { PortalAccount } from "@shared/types";
import { AccountWorkspaceHeader } from "@features/accounts/AccountWorkspaceHeader";
import { EmptyState, Panel } from "@shared/ui";

interface AgentScreenProps {
  /**
   * Resolved by the account route guard, which has already established that
   * the backend marks this account writable. This screen never re-decides
   * that, and never infers it from the entity name.
   */
  readonly account: PortalAccount;
}

/**
 * Dossier automation for one writable account.
 *
 * Wording note for later steps: plan preparation is not a "simulation". It
 * performs no write, but it does read SinAuto for identity verification, so
 * employee-facing copy must never imply the portal is left untouched. The
 * canonical sentence about writes stays exactly: "Aucune écriture n'a été
 * effectuée sur SinAuto."
 *
 * The staged workflow is deliberately not collapsed into a single action, so
 * this screen stays empty until each stage can be built as its own step.
 */
export function AgentScreen({ account }: AgentScreenProps) {
  return (
    <div className="u-stack-5">
      <AccountWorkspaceHeader title="Agent dossier" resolution={{ status: "resolved", account }} />

      <Panel
        title="Automatisation"
        description="Le remplissage s'arrête toujours avant la validation finale dans SinAuto."
      >
        <EmptyState title="Aucune automatisation disponible">
          Le dépôt du dossier, la préparation du plan et l'autorisation d'exécution arriveront aux
          étapes suivantes.
        </EmptyState>
      </Panel>
    </div>
  );
}
