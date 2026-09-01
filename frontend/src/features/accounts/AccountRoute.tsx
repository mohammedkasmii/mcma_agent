import type { ReactNode } from "react";
import { useParams } from "react-router-dom";
import type { PortalAccount } from "@shared/types";
import { EmptyState, Panel } from "@shared/ui";
import { AccountWorkspaceHeader } from "./AccountWorkspaceHeader";
import { useAccountResolution } from "./queries";

interface AccountRouteProps {
  /** Screen title, shown in every state so the employee keeps their bearings. */
  readonly title: string;
  /**
   * When true the screen renders only for an account the backend marks
   * writable. Used by the agent route.
   */
  readonly requireWritable?: boolean;
  readonly children: (account: PortalAccount) => ReactNode;
}

/**
 * The enforcement point for account-scoped routes.
 *
 * Hiding a navigation link is presentation, not protection: an employee can
 * type or bookmark /accounts/<id>/agent for any id. This guard is what
 * actually decides, and it fails closed in every direction it can:
 *
 *  - list still loading  -> nothing account-specific renders,
 *  - list failed to load -> the error is shown, not assumed benign,
 *  - account not in list -> unavailable, never "probably yours",
 *  - account not writable -> the agent screen does not render at all.
 *
 * The decision reads the backend's `writable` field. It never infers
 * capability from the entity name.
 *
 * The backend remains the real boundary: it re-checks writability on every
 * job endpoint. This guard exists so the interface tells the truth before
 * the employee gets that far.
 */
export function AccountRoute({ title, requireWritable = false, children }: AccountRouteProps) {
  const { accountId } = useParams();
  const resolution = useAccountResolution(accountId);

  if (resolution.status === "resolved" && (!requireWritable || resolution.account.writable)) {
    return <>{children(resolution.account)}</>;
  }

  return (
    <div className="u-stack-5">
      <AccountWorkspaceHeader title={title} resolution={resolution} />
      {resolution.status === "loading" ? (
        <Panel title="Chargement">
          <p className="t-secondary" aria-busy="true">
            Chargement des comptes portail…
          </p>
        </Panel>
      ) : null}
      {resolution.status === "error" ? (
        <Panel title="Comptes indisponibles">
          <EmptyState title="Impossible de charger vos comptes">{resolution.error.message}</EmptyState>
        </Panel>
      ) : null}
      {resolution.status === "unknown" ? (
        <Panel title="Compte indisponible">
          <EmptyState title="Ce compte n'est pas disponible">
            Il n'existe pas ou ne vous est pas attribué. Choisissez un compte dans la liste à gauche.
          </EmptyState>
        </Panel>
      ) : null}
      {resolution.status === "resolved" ? (
        <Panel title="Automatisation indisponible">
          <EmptyState title="Ce compte est en lecture seule">
            Aucune automatisation ne peut être lancée sur ce compte. Sa file de travail reste
            accessible.
          </EmptyState>
        </Panel>
      ) : null}
    </div>
  );
}
