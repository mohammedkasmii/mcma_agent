import { Link } from "react-router-dom";
import type { AccountsLoadState, Job, PortalAccount } from "@shared/types";
import { StatusBadge } from "@shared/ui";
import { formatAccountIdentity } from "@shared/utils/accountIdentity";
import { isHumanHandoff, isOperatorActive, jobStatusLabel, jobStatusTone } from "@shared/utils/jobStatus";
import { accountAgentJobPath } from "@shared/utils/routes";
import { useAccountRail } from "@features/accounts/useAccountRail";
import { useGlobalJobsQuery } from "./queries";
import styles from "./ActiveRunBanner.module.css";

/**
 * The runs that still need an operator, wherever they are.
 *
 * A run's account is backend truth and is read from the job, never from the
 * route: an employee looking at one agency must still see that a run is
 * waiting on another. Identity is resolved against the account collection so
 * the banner shows a real name rather than an opaque id.
 *
 * Only execution jobs appear. A dry run writes nothing and must not sit in the
 * shell looking like one that does.
 *
 * Every active run is listed. Showing the first and hiding the rest would
 * quietly strand whichever account came second.
 *
 * A failed read is not "nothing is running". The two are reported
 * differently, because an employee who sees an empty shell concludes the
 * agent is idle.
 */
export function ActiveRunBanner() {
  const jobs = useGlobalJobsQuery();
  const { state: accountsState, accounts } = useAccountRail();

  if (jobs.isError) {
    return (
      <aside className={styles.banner} aria-label="Runs en cours">
        <p className={styles.heading} role="status">
          Runs actifs
        </p>
        <p className={styles.degraded}>
          Impossible de vérifier les runs actifs. Cet écran ne peut pas confirmer qu'aucun run
          n'est en cours.
        </p>
      </aside>
    );
  }

  const active = (jobs.data ?? []).filter(
    (job) => job.mode === "EXECUTE" && isOperatorActive(job.status),
  );

  if (active.length === 0) return null;

  // Oldest first, by the backend's own createdAt. No invented priority.
  const ordered = [...active].sort((a, b) => a.createdAt.localeCompare(b.createdAt));
  const needsAttention = ordered.some((job) => isHumanHandoff(job.status));

  return (
    <aside
      className={needsAttention ? `${styles.banner} ${styles.attention}` : styles.banner}
      aria-label="Runs en cours"
    >
      <p className={styles.heading} role="status">
        {ordered.length === 1
          ? "Run d'exécution en cours"
          : `${ordered.length} runs d'exécution en cours`}
      </p>
      <ul className={styles.list}>
        {ordered.map((job) => (
          <ActiveRunRow
            key={job.jobId}
            job={job}
            accounts={accounts}
            accountsState={accountsState}
          />
        ))}
      </ul>
    </aside>
  );
}

function ActiveRunRow({
  job,
  accounts,
  accountsState,
}: {
  readonly job: Job;
  readonly accounts: readonly PortalAccount[];
  readonly accountsState: AccountsLoadState;
}) {
  const account = accounts.find((candidate) => candidate.accountId === job.accountId);

  /**
   * A write execution on an account the backend marks read-only should not
   * exist — MAMDA automation is refused server-side. If one is ever reported,
   * the row stays visible so the anomaly is not hidden, but no agent route is
   * offered for it: nothing in this frontend may hand a read-only account an
   * agent action, however the state arose.
   */
  const readOnlyAnomaly = account !== undefined && !account.writable;
  const canOpen = account !== undefined && !readOnlyAnomaly;

  return (
    <li className={styles.row}>
      <span className={styles.identity}>
        {/* An account that has not loaded yet and one that is missing from a
            loaded list are different facts, and "en cours de chargement"
            would stay on screen forever in the second case. Neither ever
            falls back to the opaque id. */}
        {account !== undefined
          ? formatAccountIdentity(account)
          : accountsState !== "loading"
            ? "Compte indisponible"
            : "Compte en cours de chargement"}
      </span>
      <StatusBadge tone={jobStatusTone(job.status)}>{jobStatusLabel(job.status)}</StatusBadge>
      {readOnlyAnomaly ? (
        <span className={styles.anomalyTag}>Exécution incohérente — compte en lecture seule</span>
      ) : null}
      {!readOnlyAnomaly && isHumanHandoff(job.status) ? (
        <span className={styles.attentionTag}>Action requise</span>
      ) : null}
      {canOpen ? (
        // Back to the run's own account, never the one being viewed.
        <Link className={styles.link} to={accountAgentJobPath(job.accountId, job.jobId)}>
          Ouvrir le run
        </Link>
      ) : null}
    </li>
  );
}
