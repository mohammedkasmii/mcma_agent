import { useState } from "react";
import { useNavigate } from "react-router-dom";
import type { PortalAccount } from "@shared/types";
import { Button, EmptyState, Panel, Section } from "@shared/ui";
import { AccountWorkspaceHeader } from "@features/accounts/AccountWorkspaceHeader";
import { toApiError } from "@features/accounts/queries";
import { formatAccountIdentity } from "@shared/utils/accountIdentity";
import { accountAgentJobPath } from "@shared/utils/routes";
import { newIdempotencyKey } from "@shared/utils/idempotency";
import { RunStepper } from "./RunStepper";
import { useStartDryRun } from "./queries";
import styles from "./AgentScreen.module.css";

interface AgentScreenProps {
  /**
   * Resolved by the account route guard, which has already established that
   * the backend marks this account writable. This screen never re-decides
   * that and never infers an account from the uploaded dossier.
   */
  readonly account: PortalAccount;
}

/** What the agent will never do. Stated before anything starts. */
const NEVER: readonly string[] = [
  "Valider ou enregistrer définitivement dans SinAuto",
  "Clôturer le dossier",
  "Finaliser le devis",
  "Déposer une pièce dans la GED",
];

type FileState =
  | { readonly kind: "none" }
  | { readonly kind: "invalid"; readonly reason: string }
  | { readonly kind: "ready"; readonly fileName: string; readonly typedInput: unknown };

/**
 * Starting a run.
 *
 * The dossier is read in the browser, parsed once, and held in memory only
 * until it is sent as the dry-run body. It is never stored, never logged and
 * never rendered: what the employee sees is the file name they chose, which
 * is enough to know they picked the right file.
 *
 * The frontend rejects only what it can honestly judge — a file it cannot
 * read, or text that is not JSON. Whether the document is a valid dossier is
 * the backend parser's decision, not this screen's.
 */
export function AgentScreen({ account }: AgentScreenProps) {
  const [file, setFile] = useState<FileState>({ kind: "none" });
  const startDryRun = useStartDryRun();
  const navigate = useNavigate();

  async function onFileChosen(chosen: File | undefined) {
    startDryRun.reset();
    if (chosen === undefined) {
      setFile({ kind: "none" });
      return;
    }
    let text: string;
    try {
      text = await chosen.text();
    } catch {
      setFile({ kind: "invalid", reason: "Ce fichier n'a pas pu être lu." });
      return;
    }
    try {
      // The parsed value is held in component state and nowhere else. The
      // parse error itself is not shown: its text quotes the document.
      setFile({ kind: "ready", fileName: chosen.name, typedInput: JSON.parse(text) as unknown });
    } catch {
      setFile({ kind: "invalid", reason: "Ce fichier n'est pas un JSON valide." });
    }
  }

  function onStart() {
    if (file.kind !== "ready") return;
    startDryRun.mutate(
      { accountId: account.accountId, typedInput: file.typedInput, idempotencyKey: newIdempotencyKey() },
      {
        onSuccess: (created) => {
          // The run lives at its own address from here on, so a reload
          // returns to it instead of losing it.
          navigate(accountAgentJobPath(account.accountId, created.jobId));
        },
      },
    );
  }

  return (
    <div className="u-stack-5">
      <AccountWorkspaceHeader title="Agent dossier" resolution={{ status: "resolved", account }} />
      <RunStepper current="new-run" />

      <Panel
        title="Nouveau run"
        description="Le dossier est préparé puis vérifié avant toute écriture."
      >
        <Section label="Compte cible" aside={formatAccountIdentity(account)}>
          <p className="t-secondary">
            Ce run s'exécutera sur {formatAccountIdentity(account)}. Le compte vient de votre
            navigation, jamais du contenu du dossier.
          </p>
        </Section>

        <Section label="Dossier Wexia">
          <label className={styles.fileLabel} htmlFor="wexia-file">
            Fichier JSON
          </label>
          <input
            id="wexia-file"
            className={styles.file}
            type="file"
            accept="application/json,.json"
            onChange={(event) => void onFileChosen(event.target.files?.[0])}
          />
          {file.kind === "ready" ? (
            <p className={styles.fileReady}>Fichier prêt : {file.fileName}</p>
          ) : null}
          {file.kind === "invalid" ? (
            <p className={styles.fileError} role="alert">
              {file.reason}
            </p>
          ) : null}
          <p className={styles.help}>
            Le contenu du dossier n'est ni affiché, ni conservé par cette application.
          </p>
        </Section>

        <Section label="Ce que l'agent ne fera pas">
          <ul className={styles.never}>
            {NEVER.map((item) => (
              <li className={styles.neverItem} key={item}>
                {item}
              </li>
            ))}
          </ul>
          <p className={styles.help}>
            Aucune validation finale ni clôture n'est effectuée automatiquement. Ces actions
            restent entièrement manuelles dans SinAuto.
          </p>
        </Section>

        <div className={styles.actions}>
          <Button
            variant="primary"
            onClick={onStart}
            disabled={file.kind !== "ready" || startDryRun.isPending}
          >
            {startDryRun.isPending ? "Préparation…" : "Préparer le plan"}
          </Button>
          <span className="t-meta">La préparation lit le portail sans jamais y écrire.</span>
        </div>

        {startDryRun.isError ? (
          <div className={styles.error} role="alert">
            <EmptyState title="La préparation n'a pas pu démarrer">
              {toApiError(startDryRun.error).message}
            </EmptyState>
          </div>
        ) : null}
      </Panel>
    </div>
  );
}
