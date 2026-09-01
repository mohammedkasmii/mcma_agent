import { AccountWorkspaceHeader } from "@features/accounts/AccountWorkspaceHeader";
import { EmptyState, Panel } from "@shared/ui";

/**
 * Dossier automation for one MCMA account.
 *
 * STEP 1 renders the frame only: no upload control, no plan preparation, no
 * plan review and no execution authorization exist yet.
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
export function AgentScreen() {
  return (
    <div className="u-stack-5">
      <AccountWorkspaceHeader title="Agent dossier" account={null} />

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
