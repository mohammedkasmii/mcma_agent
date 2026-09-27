import { useState } from "react";
import type { FormEvent } from "react";
import { Button, Panel, StatusBadge } from "@shared/ui";
import type { PendingEnrollment, Runner } from "@shared/types";
import { formatTimestamp } from "@shared/utils/datetime";
import {
  RUNNER_STATUS_LABELS,
  RUNNER_STATUS_TONES,
  SESSION_STATE_LABELS,
  runnerAccountName,
} from "@shared/utils/runnerLabels";
import { errorOf } from "@features/admin/queries";
import { useCreateEnrollment, useRevokeRunner, useRunnerOverviewQuery } from "./queries";
import styles from "./AdminRunners.module.css";

const REQUIRED_ACCOUNTS = ["acct-mcma-oujda", "acct-mcma-nador"] as const;

export function AdminRunnersScreen() {
  const overview = useRunnerOverviewQuery();
  const [actionError, setActionError] = useState<string | null>(null);

  return (
    <div className="u-stack-5">
      <h1 className="t-screen-title">Postes agents</h1>
      <p className="t-secondary">
        Un poste agent est l'application installée sur le poste d'un employé. Il exécute les
        actions sur le portail MCMA depuis ce poste. Le statut est déterminé par le serveur.
      </p>

      <Panel title="Générer un code d'association">
        <PairingForm employees={overview.data?.eligibleEmployees ?? []} />
      </Panel>

      <Panel title="Associations en attente">
        {overview.data && overview.data.pendingEnrollments.length === 0 ? (
          <p className="t-secondary">Aucune association en attente.</p>
        ) : null}
        <ul className={styles.list} aria-label="Associations en attente">
          {overview.data?.pendingEnrollments.map((item) => (
            <PendingRow key={item.enrollmentId} item={item} />
          ))}
        </ul>
      </Panel>

      <Panel title="Postes">
        {actionError === null ? null : (
          <p role="alert" className={styles.error}>
            {actionError}
          </p>
        )}
        {overview.isPending ? <p role="status">Chargement des postes…</p> : null}
        {overview.isError && overview.data === undefined ? (
          <p role="alert" className={styles.error}>
            {errorOf(overview.error).message}
          </p>
        ) : null}
        {overview.data && overview.data.runners.length === 0 ? (
          <p className="t-secondary">Aucun poste agent enregistré.</p>
        ) : null}
        <ul className={styles.list} aria-label="Liste des postes agents">
          {overview.data?.runners.map((runner) => (
            <RunnerRow key={runner.runnerId} runner={runner} onError={setActionError} />
          ))}
        </ul>
      </Panel>
    </div>
  );
}

function PendingRow({ item }: { readonly item: PendingEnrollment }) {
  return (
    <li className={styles.row}>
      <span className={styles.name}>{item.targetUsername}</span>
      <span>{item.runnerLabel ?? "Sans libellé"}</span>
      <span className="t-secondary">Expire le {formatTimestamp(item.expiresAt) ?? item.expiresAt}</span>
    </li>
  );
}

function RunnerRow({
  runner,
  onError,
}: {
  readonly runner: Runner;
  readonly onError: (message: string | null) => void;
}) {
  const revoke = useRevokeRunner();
  const [confirming, setConfirming] = useState(false);
  const who = `${runner.username}${runner.runnerLabel === null ? "" : ` (${runner.runnerLabel})`}`;

  function confirm() {
    if (revoke.isPending) return;
    onError(null);
    revoke.mutate(runner.runnerId, {
      onSuccess: () => setConfirming(false),
      onError: (caught) => {
        setConfirming(false);
        onError(errorOf(caught).message);
      },
    });
  }

  return (
    <li className={styles.row}>
      <div className={styles.rowHead}>
        <span className={styles.name}>{runner.username}</span>
        <span>{runner.runnerLabel ?? "Sans libellé"}</span>
        <StatusBadge tone={RUNNER_STATUS_TONES[runner.status]}>
          {RUNNER_STATUS_LABELS[runner.status]}
        </StatusBadge>
        <span className="t-secondary">
          {runner.status === "REVOKED"
            ? `Révoqué le ${formatTimestamp(runner.revokedAt) ?? "—"}`
            : `Dernière activité : ${formatTimestamp(runner.lastSeenAt) ?? "jamais"}`}
        </span>
      </div>
      {runner.status === "REVOKED" ? null : (
        <ul className={styles.sessions} aria-label={`Sessions de ${runner.username}`}>
          {REQUIRED_ACCOUNTS.map((accountId) => {
            const state =
              runner.sessions.find((session) => session.accountId === accountId)?.state ??
              "NOT_CONFIGURED";
            return (
              <li key={accountId}>
                {runnerAccountName(accountId)} : {SESSION_STATE_LABELS[state]}
              </li>
            );
          })}
        </ul>
      )}
      {runner.status === "REVOKED" ? null : confirming ? (
        <div className={styles.confirm} role="group" aria-label={`Confirmer la révocation de ${who}`}>
          <p>Révoquer le poste de {who} ? Ce poste ne pourra plus se connecter.</p>
          <div className={styles.actions}>
            <Button variant="primary" onClick={confirm} disabled={revoke.isPending}>
              Confirmer la révocation
            </Button>
            <Button onClick={() => setConfirming(false)} disabled={revoke.isPending}>
              Annuler
            </Button>
          </div>
        </div>
      ) : (
        <div className={styles.actions}>
          <Button onClick={() => setConfirming(true)} aria-label={`Révoquer le poste de ${who}`}>
            Révoquer
          </Button>
        </div>
      )}
    </li>
  );
}

function PairingForm({
  employees,
}: {
  readonly employees: readonly { readonly userId: string; readonly username: string }[];
}) {
  // The code lives here and nowhere else: not in the query cache, not in any
  // storage, not in the URL. Unmounting the page drops it.
  const [code, setCode] = useState<string | null>(null);
  const [copyNote, setCopyNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [target, setTarget] = useState("");
  const [label, setLabel] = useState("");
  const create = useCreateEnrollment(setCode);

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (create.isPending || target === "") return;
    setError(null);
    setCode(null);
    setCopyNote(null);
    const trimmed = label.trim();
    create.mutate(
      { targetUserId: target, ...(trimmed === "" ? {} : { runnerLabel: trimmed }) },
      {
        onSuccess: () => {
          setLabel("");
          setTarget("");
        },
        onError: (caught) => setError(errorOf(caught).message),
      },
    );
  }

  async function copy() {
    if (code === null) return;
    try {
      await navigator.clipboard.writeText(code);
      setCopyNote("Code copié.");
    } catch {
      setCopyNote("Copie impossible : sélectionnez le code et copiez-le manuellement.");
    }
  }

  function hide() {
    setCode(null);
    setCopyNote(null);
  }

  return (
    <div className="u-stack-4">
      <form className="u-stack-4" onSubmit={onSubmit} aria-label="Générer un code d'association">
        <div className={styles.field}>
          <label htmlFor="pair-employee">Employé</label>
          <select
            id="pair-employee"
            className={styles.input}
            value={target}
            onChange={(e) => setTarget(e.target.value)}
            required
          >
            <option value="">Choisir un employé</option>
            {employees.map((employee) => (
              <option key={employee.userId} value={employee.userId}>
                {employee.username}
              </option>
            ))}
          </select>
        </div>
        <div className={styles.field}>
          <label htmlFor="pair-label">Libellé du poste (facultatif)</label>
          <input
            id="pair-label"
            className={styles.input}
            maxLength={40}
            autoComplete="off"
            value={label}
            onChange={(e) => setLabel(e.target.value)}
          />
        </div>
        {error === null ? null : (
          <p role="alert" className={styles.error}>
            {error}
          </p>
        )}
        <Button type="submit" variant="primary" disabled={create.isPending || target === ""}>
          Générer un code d'association
        </Button>
      </form>

      {code === null ? null : (
        <div className={styles.codeBox} role="group" aria-label="Code d'association">
          <p className={styles.warning}>
            Ce code n'est affiché qu'une seule fois et expire dans 10 minutes.
          </p>
          <code className={styles.code} data-testid="pairing-code">
            {code}
          </code>
          <div className={styles.actions}>
            <Button onClick={() => void copy()}>Copier</Button>
            <Button onClick={hide}>Masquer le code</Button>
          </div>
          {copyNote === null ? null : <p role="status">{copyNote}</p>}
        </div>
      )}
    </div>
  );
}
