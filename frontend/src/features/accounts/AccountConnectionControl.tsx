import type { PortalAccount } from "@shared/types";
import { Button } from "@shared/ui";
import { toApiError, useRefreshNotifications, useStartLogin } from "./queries";
import styles from "./AccountConnectionControl.module.css";

interface AccountConnectionControlProps {
  readonly account: PortalAccount;
}

/**
 * The one control an employee needs to get an account working: connect it,
 * reconnect it, or pull its notifications again.
 *
 * Clicking "Se connecter" does not sign anyone in. It asks the backend to
 * open the real SinAuto window on this machine; the employee types their
 * username, password and OTP into the portal's own page. No credential ever
 * reaches this application, which is why there is no form here.
 *
 * Available for every account, including read-only ones: connecting a MAMDA
 * profile is how its notifications are read. That is unrelated to portal
 * automation, which MAMDA still never gets.
 *
 * Nothing here decides the resulting state. Both actions refetch the account
 * list and render whatever the backend then reports.
 */
export function AccountConnectionControl({ account }: AccountConnectionControlProps) {
  const login = useStartLogin(account.accountId);
  const refresh = useRefreshNotifications(account.accountId);

  const state = account.connectionState;
  const connected = state === "CONNECTED";
  const unverified = state === "UNVERIFIED";

  // "Vérifier" is the refresh: it opens the stored session and probes it.
  // An unverified account is NOT an expired one, so the first thing
  // offered must not be a username, password and OTP for a session that
  // may be perfectly good. Reconnecting stays available underneath for
  // when checking keeps coming back inconclusive.
  const primary = connected || unverified ? refresh : login;
  const primaryLabel = connected
    ? "Actualiser"
    : unverified
      ? "Vérifier"
      : state === "RECONNECT_REQUIRED"
        ? "Reconnecter"
        : "Se connecter";
  const primaryPendingLabel = connected
    ? "Actualisation…"
    : unverified
      ? "Vérification…"
      : "Connexion…";

  const busy = login.isPending || refresh.isPending;

  return (
    <div className={styles.control}>
      <Button
        className={styles.button}
        // Disabled while in flight, so a second click cannot open a second
        // portal window or start a second poll on the same account.
        disabled={busy}
        onClick={() => primary.mutate()}
      >
        {primary.isPending ? primaryPendingLabel : primaryLabel}
      </Button>

      {unverified ? (
        <Button className={styles.secondary} disabled={busy} onClick={() => login.mutate()}>
          {login.isPending ? "Connexion…" : "Reconnecter"}
        </Button>
      ) : null}

      {unverified && !busy ? (
        <p className={styles.hint}>
          Une session est enregistrée pour ce compte, sans confirmation qu'elle est encore valide.
        </p>
      ) : null}

      {!connected && !unverified && login.isPending ? (
        <p className={styles.hint} role="status">
          Terminez la connexion dans la fenêtre SinAuto qui s'ouvre.
        </p>
      ) : null}

      {connected && refresh.isSuccess && !refresh.isPending ? (
        // The backend's own sentence, chosen from its fixed allowlist.
        <p className={styles.hint} role="status">
          {refresh.data.message}
        </p>
      ) : null}

      {login.isError || refresh.isError ? (
        <p className={styles.error} role="alert">
          {toApiError(login.error ?? refresh.error).message}
        </p>
      ) : null}
    </div>
  );
}
