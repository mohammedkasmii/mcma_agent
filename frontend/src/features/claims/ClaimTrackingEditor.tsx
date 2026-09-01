import { useState } from "react";
import type { Claim, ClaimStatus } from "@shared/types";
import { CLAIM_STATUSES } from "@shared/types";
import { Button, Section } from "@shared/ui";
import { NOTE_MAX_LENGTH } from "@shared/api/claims";
import { claimStatusLabel } from "@shared/utils/claimStatus";
import { toApiError } from "@features/accounts/queries";
import { formatTimestamp } from "@shared/utils/datetime";
import { useSaveTracking } from "./queries";
import styles from "./ClaimTrackingEditor.module.css";

interface ClaimTrackingEditorProps {
  readonly accountId: string;
  readonly claim: Claim;
}

/**
 * The employee's own tracking of a claim: a status and an optional note.
 *
 * This is an action of this application, not of the portal. It is called
 * "Enregistrer le suivi" precisely so it can never be mistaken for SinAuto's
 * own Enregistrer, and it validates, closes or files nothing.
 *
 * Available on every account. A MAMDA account is read-only for portal
 * automation; its claims are still tracked here by an employee, and the two
 * are not the same restriction.
 */
export function ClaimTrackingEditor({ accountId, claim }: ClaimTrackingEditorProps) {
  const [status, setStatus] = useState<ClaimStatus>(claim.status);
  const [note, setNote] = useState<string>(claim.note ?? "");
  const save = useSaveTracking(accountId);

  const tooLong = note.length > NOTE_MAX_LENGTH;
  const remaining = NOTE_MAX_LENGTH - note.length;

  function onSave() {
    if (tooLong) return;
    // An empty box means "no note", which the backend expresses as null
    // rather than an empty string.
    const trimmed = note.trim();
    save.mutate({ claimPk: claim.claimPk, status, note: trimmed.length === 0 ? null : trimmed });
  }

  const savedAt = formatTimestamp(claim.updatedAt);

  return (
    <Section label="Suivi employé">
      <div className={styles.field}>
        <label className={styles.label} htmlFor="claim-status">
          Statut
        </label>
        <select
          id="claim-status"
          className={styles.control}
          value={status}
          onChange={(event) => setStatus(event.target.value as ClaimStatus)}
        >
          {CLAIM_STATUSES.map((value) => (
            <option key={value} value={value}>
              {claimStatusLabel(value)}
            </option>
          ))}
        </select>
      </div>

      <div className={styles.field}>
        <label className={styles.label} htmlFor="claim-note">
          Note
        </label>
        <textarea
          id="claim-note"
          className={styles.control}
          rows={4}
          value={note}
          maxLength={undefined}
          aria-describedby="claim-note-counter"
          onChange={(event) => setNote(event.target.value)}
        />
        <p
          id="claim-note-counter"
          className={tooLong ? styles.counterOver : styles.counter}
        >
          {tooLong
            ? `${-remaining} caractères de trop (maximum ${NOTE_MAX_LENGTH}).`
            : `${remaining} caractères restants`}
        </p>
      </div>

      <div className={styles.actions}>
        <Button variant="primary" onClick={onSave} disabled={tooLong || save.isPending}>
          {save.isPending ? "Enregistrement…" : "Enregistrer le suivi"}
        </Button>
        {save.isSuccess && !save.isPending ? (
          <span className={styles.confirmed}>
            Suivi enregistré{savedAt === null ? "" : ` · ${savedAt}`}
          </span>
        ) : null}
      </div>

      {save.isError ? (
        // The draft above is untouched on failure: the employee keeps the
        // note they wrote instead of retyping it.
        <p className={styles.error} role="alert">
          {toApiError(save.error).message}
        </p>
      ) : null}

      <p className={styles.help}>
        Le statut et la note appartiennent à cette application. Aucune écriture n'est effectuée sur
        SinAuto.
      </p>
    </Section>
  );
}
