import type { Claim } from "@shared/types";
import { StatusBadge } from "@shared/ui";
import { claimStatusLabel, claimStatusTone } from "@shared/utils/claimStatus";
import styles from "./ClaimList.module.css";

interface ClaimListProps {
  readonly claims: readonly Claim[];
}

/** A field the portal did not supply. Shown as absence, never as an empty cell. */
function Missing() {
  return <span className={styles.missing}>—</span>;
}

function Field({ value }: { readonly value: string | null }) {
  return value === null || value.length === 0 ? <Missing /> : <>{value}</>;
}

/**
 * The claims of one account, one row each.
 *
 * Rows lead with the portal reference and the insured, because those are what
 * an employee matches against a dossier in front of them. The internal
 * claim_pk and the portal's own claim id are never drawn — they are keys and
 * future action targets, not identity an employee reads.
 *
 * All values render as text. Portal-supplied strings are data, never markup.
 */
export function ClaimList({ claims }: ClaimListProps) {
  return (
    <table className={styles.table}>
      <caption className="u-visually-hidden">
        Sinistres du compte, avec leur suivi employé
      </caption>
      <thead>
        <tr>
          <th scope="col">Référence</th>
          <th scope="col">Assuré</th>
          <th scope="col">Immatriculation</th>
          <th scope="col">Police</th>
          <th scope="col">Alertes</th>
          <th scope="col">Suivi</th>
          <th scope="col">Dernière note</th>
        </tr>
      </thead>
      <tbody>
        {claims.map((claim) => (
          <tr key={claim.claimPk}>
            <td className="t-data">
              <Field value={claim.reference} />
            </td>
            <td>
              <Field value={claim.insured} />
            </td>
            <td className="t-data">
              <Field value={claim.matricule} />
            </td>
            <td className="t-data">
              <Field value={claim.police} />
            </td>
            <td>
              {claim.categories.length === 0 ? (
                <Missing />
              ) : (
                <ul className={styles.categories}>
                  {claim.categories.map((category) => (
                    <li className={styles.category} key={category}>
                      {category}
                    </li>
                  ))}
                </ul>
              )}
            </td>
            <td>
              <StatusBadge tone={claimStatusTone(claim.status)}>
                {claimStatusLabel(claim.status)}
              </StatusBadge>
            </td>
            <td>
              {claim.note === null ? (
                <Missing />
              ) : (
                <>
                  <span className={styles.note}>{claim.note}</span>
                  {claim.updatedAt === null ? null : (
                    <span className={styles.noteMeta}>{claim.updatedAt}</span>
                  )}
                </>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
