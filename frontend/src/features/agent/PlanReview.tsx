import type { JobPlan, PortalAccount } from "@shared/types";
import { Section } from "@shared/ui";
import { formatAccountIdentity } from "@shared/utils/accountIdentity";
import styles from "./PlanReview.module.css";

interface PlanReviewProps {
  readonly account: PortalAccount;
  readonly plan: JobPlan;
}

/**
 * What the agent will type, shown exactly as the backend returned it.
 *
 * Amounts are printed as the strings they arrived as. Nothing is summed,
 * reformatted or rounded: a total computed here could differ from what is
 * actually written, and a reviewed plan that does not match the writing is
 * worse than no review at all.
 *
 * Rubriques show their real identifier. There is no trusted label mapping in
 * this frontend, and inventing readable names for accounting codes would put
 * words in the backend's mouth.
 */
export function PlanReview({ account, plan }: PlanReviewProps) {
  const summary = `${formatAccountIdentity(account)} · ${plan.steps.length} rubriques · ${plan.fieldIntents.length} champs`;

  return (
    <>
      <Section label="Workflow détecté" aside={plan.repairWorkflow}>
        <p className="t-secondary">
          L'agent saisira les rubriques et champs présentés dans ce plan, puis s'arrêtera pour
          vérification humaine.
        </p>
        <p className={styles.summary}>{summary}</p>
      </Section>

      <Section label="Rubriques prévues" aside={`${plan.steps.length} rubriques`}>
        {plan.steps.length === 0 ? (
          <p className={styles.empty}>Aucune rubrique dans ce plan.</p>
        ) : (
          <table className={styles.table}>
            <thead>
              <tr>
                <th scope="col">Rubrique</th>
                <th scope="col" className={styles.numeric}>
                  Montant HT
                </th>
                <th scope="col" className={styles.numeric}>
                  TVA
                </th>
                <th scope="col" className={styles.numeric}>
                  Vétusté
                </th>
              </tr>
            </thead>
            <tbody>
              {plan.steps.map((step) => (
                <tr key={`${step.rubriqueId}-${step.ht}-${step.tva}`}>
                  <td className="t-data">{step.rubriqueId}</td>
                  <td className={`t-data ${styles.numeric}`}>{step.ht}</td>
                  <td className={`t-data ${styles.numeric}`}>{step.tva}</td>
                  <td className={`t-data ${styles.numeric}`}>{step.vetuste}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>

      <Section label="Champs du formulaire" aside={`${plan.fieldIntents.length} champs`}>
        {plan.fieldIntents.length === 0 ? (
          <p className={styles.empty}>Aucun champ supplémentaire dans ce plan.</p>
        ) : (
          <ul className={styles.fields}>
            {plan.fieldIntents.map((intent) => (
              <li className={styles.field} key={`${intent.selector}-${intent.value}`}>
                <span className={`t-data ${styles.selector}`}>{intent.selector}</span>
                <span className={styles.fieldValue}>{intent.value}</span>
              </li>
            ))}
          </ul>
        )}
        <p className={styles.help}>
          Valeurs telles qu'elles seront saisies dans la mission ouverte, sans validation.
        </p>
      </Section>

      <Section label="Empreinte du plan">
        <p className={`t-data ${styles.hash}`}>{plan.planHash}</p>
      </Section>
    </>
  );
}
