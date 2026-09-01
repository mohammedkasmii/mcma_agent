import { Panel, EmptyState } from "@shared/ui";

/**
 * The entry screen: what needs attention, across every account the employee
 * can see. It answers "where do I go next", not "here are some metrics".
 *
 * STEP 1 renders the structure only — no account, claim or job data is
 * fetched, and nothing here invents a record to fill the space.
 */
export function OverviewScreen() {
  return (
    <div className="u-stack-5">
      <header>
        <h1 className="t-screen-title">Vue d'ensemble</h1>
        <p className="t-secondary">
          L'état de vos comptes portail et les dossiers qui attendent une action.
        </p>
      </header>

      <Panel
        title="Comptes portail"
        description="État de connexion et volume de travail par compte."
      >
        <EmptyState title="Comptes non chargés">
          Les comptes apparaîtront ici dès que la liste sera reliée au serveur.
        </EmptyState>
      </Panel>

      <Panel title="Action requise" description="Dossiers arrêtés en attente d'un employé.">
        <EmptyState title="Rien à traiter pour le moment">
          Les dossiers arrêtés pour revue humaine s'afficheront ici.
        </EmptyState>
      </Panel>
    </div>
  );
}
