import type { PortalAccount } from "@shared/types";
import { StatusBadge } from "@shared/ui";
import { formatTimestamp } from "@shared/utils/datetime";
import styles from "./NotificationFreshness.module.css";

/** Only the poll fields: this renders no account identity of its own. */
type FreshnessFields = Pick<
  PortalAccount,
  "notificationLastAttemptStatus" | "notificationLastSuccessAt"
>;

interface NotificationFreshnessProps {
  readonly account: FreshnessFields;
}

/**
 * How much the notifications on screen can be trusted right now.
 *
 * Two separate facts, never merged: WHEN the last successful refresh was,
 * and whether the LATEST attempt actually worked. A failed attempt does not
 * move the "as of" time — it adds a warning next to it, because the rows the
 * employee is looking at genuinely still date from the last success.
 *
 * No "next refresh at ..." is shown anywhere: the background poll loop
 * exposes no authoritative schedule, and inventing one would be a promise
 * this application cannot keep.
 */
export function NotificationFreshness({ account }: NotificationFreshnessProps) {
  const lastSuccess = formatTimestamp(account.notificationLastSuccessAt);
  const status = account.notificationLastAttemptStatus;
  const failed = status === "FAILED";
  const partial = status === "PARTIAL";

  return (
    <div className={styles.freshness}>
      <p className={styles.line}>
        {lastSuccess === null
          ? "Jamais actualisé avec succès."
          : `Actualisé le ${lastSuccess}.`}
      </p>
      {failed || partial ? (
        <p className={styles.warning}>
          <StatusBadge tone={failed ? "failed" : "review"}>
            {failed ? "Dernière tentative échouée" : "Dernière tentative incomplète"}
          </StatusBadge>
          <span className={styles.warningText}>
            {failed
              ? lastSuccess === null
                ? "Aucune actualisation n'a encore abouti : cette liste peut être vide ou incomplète."
                : "Les notifications affichées datent de la dernière actualisation réussie."
              : "Certaines catégories n'ont pas pu être lues. Des notifications peuvent manquer."}
          </span>
        </p>
      ) : null}
    </div>
  );
}
