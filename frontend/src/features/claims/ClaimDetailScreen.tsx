import { Link, useParams } from "react-router-dom";
import type { PortalAccount } from "@shared/types";
import { EmptyState, Panel, Section, Skeleton, StatusBadge } from "@shared/ui";
import { AccountWorkspaceHeader } from "@features/accounts/AccountWorkspaceHeader";
import { toApiError } from "@features/accounts/queries";
import { claimStatusLabel, claimStatusTone } from "@shared/utils/claimStatus";
import { formatTimestamp } from "@shared/utils/datetime";
import { accountWorkPath } from "@shared/utils/routes";
import { ClaimTrackingEditor } from "./ClaimTrackingEditor";
import { useClaimResolution } from "./queries";
import styles from "./ClaimDetailScreen.module.css";

interface ClaimDetailScreenProps {
  /** Resolved by the account route guard before this screen mounts. */
  readonly account: PortalAccount;
}

function Value({ value }: { readonly value: string | null }) {
  return value === null || value.length === 0 ? (
    <span className={styles.missing}>—</span>
  ) : (
    <>{value}</>
  );
}

/**
 * One claim, resolved from the account's authoritative list.
 *
 * There is no per-claim endpoint, so a reloaded or pasted link resolves the
 * account first, loads that account's claims, and finds this one among them.
 * A claim that is not in the list is unavailable — never assumed to exist,
 * and never fetched from another account's list.
 *
 * The claimPk in the address is a handle, not identity. What the employee
 * reads is the portal reference and the insured.
 */
export function ClaimDetailScreen({ account }: ClaimDetailScreenProps) {
  const { claimPk } = useParams();
  const resolution = useClaimResolution(account.accountId, claimPk);

  return (
    <div className="u-stack-5">
      <AccountWorkspaceHeader title="Dossier" resolution={{ status: "resolved", account }} />

      <p className={styles.back}>
        <Link to={accountWorkPath(account.accountId)}>← Revenir à la file de travail</Link>
      </p>

      {resolution.status === "loading" ? (
        <Panel title="Dossier">
          <div aria-busy="true" className="u-stack-2">
            <span className="u-visually-hidden">Chargement du dossier</span>
            <Skeleton size="md" />
            <Skeleton size="lg" />
            <Skeleton size="sm" />
          </div>
        </Panel>
      ) : null}

      {resolution.status === "error" ? (
        <Panel title="Dossier indisponible">
          <EmptyState title="Impossible de charger ce dossier">
            {toApiError(resolution.error).message}
          </EmptyState>
        </Panel>
      ) : null}

      {resolution.status === "unknown" ? (
        <Panel title="Dossier indisponible">
          <EmptyState title="Ce dossier n'est pas disponible">
            Il n'existe pas dans la file de ce compte. Revenez à la file de travail pour le
            retrouver.
          </EmptyState>
        </Panel>
      ) : null}

      {resolution.status === "resolved" ? (
        <>
          <Panel
            title={resolution.claim.reference ?? "Référence absente"}
            description={resolution.claim.insured ?? undefined}
            aside={
              <StatusBadge tone={claimStatusTone(resolution.claim.status)}>
                {claimStatusLabel(resolution.claim.status)}
              </StatusBadge>
            }
          >
            <Section label="Données portail" aside="Lecture seule">
              <dl className={styles.grid}>
                {/* Reference and insured head the panel above; repeating them
                    here would be two copies of the same fact. */}
                <div>
                  <dt className={styles.term}>Police</dt>
                  <dd className={`t-data ${styles.value}`}>
                    <Value value={resolution.claim.police} />
                  </dd>
                </div>
                <div>
                  <dt className={styles.term}>Immatriculation</dt>
                  <dd className={`t-data ${styles.value}`}>
                    <Value value={resolution.claim.matricule} />
                  </dd>
                </div>
              </dl>
              <p className={styles.help}>
                Ces champs proviennent du portail et ne sont pas modifiables ici.
              </p>
            </Section>

            <Section label="Catégories d'alerte">
              {resolution.claim.categories.length === 0 ? (
                <p className={styles.missing}>Aucune catégorie active.</p>
              ) : (
                <ul className={styles.chips}>
                  {resolution.claim.categories.map((category) => (
                    <li className={styles.chip} key={category}>
                      {category}
                    </li>
                  ))}
                </ul>
              )}
            </Section>

            {/* The note itself is not echoed here: the editor below is
                pre-filled with it, and two copies of the same text invite
                editing the wrong one. */}
            <Section label="Dernier suivi enregistré">
              <p className={styles.value}>
                {resolution.claim.updatedAt === null ? (
                  <span className={styles.missing}>Aucun suivi enregistré pour ce dossier.</span>
                ) : (
                  `${claimStatusLabel(resolution.claim.status)} · ${formatTimestamp(resolution.claim.updatedAt)}`
                )}
              </p>
            </Section>
          </Panel>

          <Panel title="Suivi employé" description="Visible dans cette application uniquement.">
            {/* Keyed by the claim: a refetch of the same claim leaves an
                active draft alone, while moving to another claim remounts
                the editor so the previous draft cannot be shown or saved
                against the new one. */}
            <ClaimTrackingEditor
              key={resolution.claim.claimPk}
              accountId={account.accountId}
              claim={resolution.claim}
            />
          </Panel>
        </>
      ) : null}
    </div>
  );
}
