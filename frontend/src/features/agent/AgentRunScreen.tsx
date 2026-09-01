import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import type { Job, JobPlan, JobStatus, PortalAccount } from "@shared/types";
import { Button, EmptyState, Panel, Section, Skeleton, StatusBadge } from "@shared/ui";
import { AccountWorkspaceHeader } from "@features/accounts/AccountWorkspaceHeader";
import { toApiError } from "@features/accounts/queries";
import { formatAccountIdentity } from "@shared/utils/accountIdentity";
import { formatTimestamp } from "@shared/utils/datetime";
import {
  canAuthorizeExecution,
  isDryRunBlocked,
  isJobInFlight,
  jobStatusLabel,
  jobStatusTone,
} from "@shared/utils/jobStatus";
import { accountAgentJobPath, accountAgentPath } from "@shared/utils/routes";
import { newIdempotencyKey } from "@shared/utils/idempotency";
import { PlanReview } from "./PlanReview";
import { RunStepper } from "./RunStepper";
import { useAuthorizeExecution, useJobPlanQuery, useJobQuery } from "./queries";
import styles from "./AgentRunScreen.module.css";

interface AgentRunScreenProps {
  readonly account: PortalAccount;
}

/**
 * One run, addressed by its job id.
 *
 * The address carries the run, so a reload returns to it rather than losing
 * it. The job itself is read from the backend on every visit; nothing about
 * its state is remembered locally.
 *
 * A job belonging to another account fails closed in the adapter before it
 * reaches this screen, so a run can never be drawn under the wrong account
 * header.
 */
export function AgentRunScreen({ account }: AgentRunScreenProps) {
  const { jobId } = useParams();
  const query = useJobQuery(jobId ?? "", account.accountId);

  if (query.isPending) {
    return (
      <RunFrame account={account} stage="plan-review">
        <Panel title="Run">
          <div aria-busy="true" className="u-stack-2">
            <span className="u-visually-hidden">Chargement du run</span>
            <Skeleton size="md" />
            <Skeleton size="lg" />
          </div>
        </Panel>
      </RunFrame>
    );
  }

  if (query.isError) {
    return (
      <RunFrame account={account} stage="plan-review">
        <Panel title="Run indisponible">
          <EmptyState title="Impossible de charger ce run">
            {toApiError(query.error).message}
          </EmptyState>
        </Panel>
      </RunFrame>
    );
  }

  const job = query.data;
  if (job === null || job === undefined) {
    return (
      <RunFrame account={account} stage="plan-review">
        <Panel title="Run indisponible">
          <EmptyState title="Ce run n'est pas disponible">
            Il n'existe pas sur ce compte. Revenez à l'agent pour en démarrer un nouveau.
          </EmptyState>
        </Panel>
      </RunFrame>
    );
  }

  return job.mode === "EXECUTE" ? (
    <ExecutionView account={account} job={job} />
  ) : (
    <DryRunView account={account} job={job} />
  );
}

function RunFrame({
  account,
  stage,
  children,
}: {
  readonly account: PortalAccount;
  readonly stage: "new-run" | "plan-review" | "execution";
  readonly children: React.ReactNode;
}) {
  return (
    <div className="u-stack-5">
      <AccountWorkspaceHeader title="Agent dossier" resolution={{ status: "resolved", account }} />
      <RunStepper current={stage} />
      {children}
      <p className={styles.back}>
        <Link to={accountAgentPath(account.accountId)}>← Revenir à l'agent</Link>
      </p>
    </div>
  );
}

function JobHeadline({ job }: { readonly job: Job }) {
  return (
    <div className={styles.headline}>
      <StatusBadge tone={jobStatusTone(job.status)}>{jobStatusLabel(job.status)}</StatusBadge>
      {job.startedAt === null ? null : (
        <span className="t-meta">Démarré {formatTimestamp(job.startedAt)}</span>
      )}
      {job.finishedAt === null ? null : (
        <span className="t-meta">Terminé {formatTimestamp(job.finishedAt)}</span>
      )}
    </div>
  );
}

/**
 * Whether the plan on screen is provably the plan this verified dry-run was
 * verified with.
 *
 * Every condition here is a reason an employee could otherwise tick "j'ai
 * relu ce plan" without the plan being in front of them, or with a different
 * plan in front of them. All of them fail closed.
 */
function isReviewablePlan(job: Job, plan: JobPlan | undefined): plan is JobPlan {
  if (plan === undefined) return false;
  // The plan must name this job...
  if (plan.jobId !== job.jobId) return false;
  // ...and match the digest recorded when the dry-run was verified. The plan
  // endpoint rebuilds its answer on demand; a different hash means the
  // rebuild produced something other than what was verified.
  if (job.planHash === null) return false;
  if (plan.planHash !== job.planHash) return false;
  // A verified dry-run should carry no review items. If one does, the two
  // facts disagree and the disagreement is not ours to resolve.
  return plan.needsReview.length === 0;
}

function DryRunView({ account, job }: { readonly account: PortalAccount; readonly job: Job }) {
  // The plan is fetched once the backend has one to give: either a verified
  // dry-run, or one stopped for review whose reasons the employee must read.
  const planNeeded = canAuthorizeExecution(job.status) || job.status === "NEEDS_REVIEW";
  const planQuery = useJobPlanQuery(account.accountId, job.jobId, planNeeded);
  // The exact plan this run was verified with, or null. Null is the only
  // state the authorization branch is allowed to see when anything is off.
  const reviewedPlan = isReviewablePlan(job, planQuery.data) ? planQuery.data : null;

  return (
    <RunFrame account={account} stage="plan-review">
      <Panel title="Préparation du plan" aside={<JobHeadline job={job} />}>
        {isJobInFlight(job.status) ? (
          <Section label="État">
            <p className="t-body" aria-live="polite">
              {jobStatusLabel(job.status)}. Cette étape lit le portail — recherche, ouverture de la
              mission, vérification d'identité — sans jamais y écrire.
            </p>
          </Section>
        ) : null}

        {canAuthorizeExecution(job.status) ? (
          <div className={styles.verified}>
            <span className={styles.verifiedTag}>Dry run terminé</span>
            <span className={styles.verifiedText}>
              Aucune écriture n’a été effectuée sur SinAuto.
            </span>
          </div>
        ) : null}

        {job.status === "IDENTITY_FAILED" ? (
          <div className={styles.blocked} role="alert">
            <p className={styles.blockedTitle}>Identité non confirmée — exécution bloquée</p>
            <p className={styles.blockedBody}>
              L'identité de la mission n'a pas pu être confirmée en lecture seule. Aucune écriture
              n'a été effectuée sur SinAuto. Reprenez le dossier manuellement dans SinAuto, ou
              relancez un run après correction.
            </p>
          </div>
        ) : null}

        {job.status === "NEEDS_REVIEW" ? (
          <div className={styles.blocked} role="alert">
            <p className={styles.blockedTitle}>Plan à vérifier — exécution bloquée</p>
            <p className={styles.blockedTag}>Aucune écriture</p>
            <p className={styles.blockedBody}>
              Le plan comporte des éléments à vérifier. Aucun remplissage ne peut être autorisé
              tant qu'ils ne sont pas levés. Reprenez le dossier dans SinAuto, ou relancez un run
              après correction du dossier.
            </p>
          </div>
        ) : null}

        {planQuery.isSuccess ? (
          <PlanReview account={account} plan={planQuery.data} />
        ) : null}

        {planNeeded && planQuery.isError ? (
          <Section label="Plan">
            <EmptyState title="Impossible de charger le plan">
              {toApiError(planQuery.error).message}
            </EmptyState>
          </Section>
        ) : null}

        {job.status === "NEEDS_REVIEW" && planQuery.isSuccess ? (
          <NeedsReviewList plan={planQuery.data} />
        ) : null}

        {/* The gate opens only for a verified dry-run that is not blocked AND
            whose exact reviewed plan is on screen. Anything else — still
            loading, failed, a different job, a different hash, or carrying
            review items — renders no checkbox and no button at all. */}
        {canAuthorizeExecution(job.status) && !isDryRunBlocked(job.status) && reviewedPlan !== null ? (
          <ExecutionAuthorization
            // Keyed by the job: the confirmation and the mutation belong to
            // this run, and must not survive a move to another one.
            key={job.jobId}
            account={account}
            job={job}
            plan={reviewedPlan}
          />
        ) : null}

        {canAuthorizeExecution(job.status) && reviewedPlan === null && planQuery.isSuccess ? (
          <Section label="Autorisation indisponible">
            <EmptyState title="Le plan affiché ne correspond pas à ce run">
              L'autorisation reste bloquée tant que le plan exact de ce run vérifié n'est pas
              disponible. Rechargez la page, ou relancez une préparation.
            </EmptyState>
          </Section>
        ) : null}

        {canAuthorizeExecution(job.status) && planQuery.isPending ? (
          <Section label="Autorisation">
            <p className="t-secondary" aria-busy="true">
              Chargement du plan. L'autorisation ne sera proposée qu'une fois le plan affiché.
            </p>
          </Section>
        ) : null}
      </Panel>
    </RunFrame>
  );
}

function NeedsReviewList({ plan }: { readonly plan: JobPlan }) {
  if (plan.needsReview.length === 0) return null;
  return (
    <Section label="Éléments à vérifier" aside={`${plan.needsReview.length}`}>
      <ul className={styles.reviewList}>
        {plan.needsReview.map((item) => (
          <li className={styles.reviewItem} key={`${item.reason}-${item.detail ?? ""}`}>
            <span className={`t-data ${styles.reviewReason}`}>{item.reason}</span>
            {item.detail === null ? null : (
              <span className={styles.reviewDetail}>{item.detail}</span>
            )}
          </li>
        ))}
      </ul>
    </Section>
  );
}

/**
 * The authorization gate.
 *
 * It renders only for a verified dry-run — there is no branch that draws it
 * for a blocked one, so there is nothing to override and no "continue anyway"
 * to find. The confirmation checkbox is a second, deliberate act by the
 * employee, and the account it names is the one resolved from the URL.
 */
function ExecutionAuthorization({
  account,
  job,
  plan,
}: {
  readonly account: PortalAccount;
  readonly job: Job;
  /** Always the verified plan for this job: the caller has checked it. */
  readonly plan: JobPlan;
}) {
  const [confirmed, setConfirmed] = useState(false);
  const authorize = useAuthorizeExecution(account.accountId, job.jobId);
  const navigate = useNavigate();

  const counts = `${formatAccountIdentity(account)} · ${plan.steps.length} rubriques · ${plan.fieldIntents.length} champs`;

  return (
    <Section label="Autorisation de remplissage" aside={counts}>
      {/* The plan sentence is stated once, in the plan itself. What belongs
          here is the limit of the authorization being given. */}
      <p className="t-secondary">
        Aucune validation finale ni clôture n'est effectuée automatiquement.
      </p>

      <label className={styles.confirm}>
        <input
          type="checkbox"
          checked={confirmed}
          onChange={(event) => setConfirmed(event.target.checked)}
        />
        <span>
          Je confirme avoir relu ce plan et j'autorise le remplissage sur le compte{" "}
          <span className="t-data">{formatAccountIdentity(account)}</span>.
        </span>
      </label>

      <div className={styles.actions}>
        <Button
          variant="primary"
          disabled={!confirmed || authorize.isPending}
          onClick={() =>
            authorize.mutate(newIdempotencyKey(), {
              onSuccess: (created) => {
                // A new job, not the parent. Routing to its own id is what
                // keeps the dry-run and the execution from being confused.
                navigate(accountAgentJobPath(account.accountId, created.jobId));
              },
            })
          }
        >
          {authorize.isPending ? "Autorisation…" : "Autoriser le remplissage"}
        </Button>
        <span className="t-meta">Prêt à autoriser</span>
      </div>

      {authorize.isError ? (
        <p className={styles.error} role="alert">
          {toApiError(authorize.error).message}
        </p>
      ) : null}
    </Section>
  );
}

/**
 * An execution job.
 *
 * Its status is the only thing known about it, and the copy says only what
 * that status supports. An execution can be stopped before any write — the
 * backend re-plans from the retained input and moves EXECUTE jobs to
 * NEEDS_REVIEW when that re-plan raises review items — so the forward-looking
 * "the agent will fill and stop for review" sentence is shown for exactly the
 * statuses where it is still true, and never as a default.
 *
 * The full execution and handoff screens belong to the next step. What this
 * must not do in the meantime is describe a stopped run as a running one.
 */
function ExecutionView({ account, job }: { readonly account: PortalAccount; readonly job: Job }) {
  // Blocked before any portal write. The re-plan raised review items, so the
  // fill never began.
  if (job.status === "NEEDS_REVIEW") {
    return (
      <RunFrame account={account} stage="execution">
        <Panel title="Exécution" aside={<JobHeadline job={job} />}>
          <div className={styles.blocked} role="alert">
            <p className={styles.blockedTitle}>Plan à vérifier — exécution bloquée</p>
            <p className={styles.blockedTag}>Aucune écriture</p>
            <p className={styles.blockedBody}>
              La préparation de l'exécution s'est arrêtée avant tout remplissage : le plan
              reconstruit comporte des éléments à vérifier. Aucun remplissage n'a commencé et aucun
              ne peut être autorisé sur ce run. Reprenez le dossier dans SinAuto, ou relancez une
              préparation après correction.
            </p>
          </div>
        </Panel>
      </RunFrame>
    );
  }

  // Stopped, failed or waiting on a person. None of these are "filling will
  // continue", and the next step builds their real screens.
  const STOPPED: Partial<Record<JobStatus, string>> = {
    IDENTITY_FAILED:
      "L'identité de la mission n'a pas pu être confirmée. Le remplissage n'a pas eu lieu.",
    WRITE_ABORTED:
      "Le remplissage a été interrompu. Vérifiez le dossier dans SinAuto avant de poursuivre manuellement.",
    INTERRUPTED_NEEDS_HUMAN_REVIEW:
      "Le run a été interrompu et demande une vérification humaine. Vérifiez le dossier dans SinAuto.",
    ABORTED_ON_RESTART:
      "Le run a été abandonné au redémarrage de l'application. Vérifiez le dossier dans SinAuto.",
    ERROR: "Le run s'est terminé en échec. Vérifiez le dossier dans SinAuto.",
    READY_FOR_HUMAN_REVIEW:
      "L'agent s'est arrêté. Vérifiez le dossier dans SinAuto avant de poursuivre manuellement.",
    AWAITING_HUMAN_CONFIRMATION:
      "L'agent s'est arrêté et attend votre confirmation. Vérifiez le dossier dans SinAuto.",
    HUMAN_CONFIRMED_COMPLETE: "Ce run a été confirmé comme vérifié.",
  };
  const stopped = STOPPED[job.status];

  return (
    <RunFrame account={account} stage="execution">
      <Panel title="Exécution" aside={<JobHeadline job={job} />}>
        <Section label="Plan autorisé">
          <p className="t-body">
            Le remplissage a été autorisé sur {formatAccountIdentity(account)}.
          </p>
          <p className={styles.help}>
            Aucune validation finale ni clôture n'est effectuée automatiquement.
          </p>
        </Section>

        <Section label="État du run" aside={jobStatusLabel(job.status)}>
          <p className="t-body" aria-live="polite">
            {stopped ?? "L'agent remplira la mission ouverte, puis s'arrêtera pour vérification humaine."}
          </p>
          {job.parentJobId === null ? null : (
            <p className={styles.help}>
              Ce run d'exécution est distinct du dry run qui l'a préparé.
            </p>
          )}
        </Section>
      </Panel>
    </RunFrame>
  );
}
