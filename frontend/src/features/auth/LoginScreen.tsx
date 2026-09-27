import { useState } from "react";
import type { FormEvent } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { Button } from "@shared/ui";
import { ApiRequestError } from "@shared/api/client";
import { safeRedirectPath } from "@shared/utils/safeRedirect";
import { useAuth } from "./AuthProvider";
import { SessionCheck } from "./RequireAuth";
import styles from "./Auth.module.css";

const EXPIRED_MESSAGE = "Votre session a expiré. Veuillez vous reconnecter.";

function errorSentence(error: unknown): string {
  if (error instanceof ApiRequestError) {
    // Unknown user and wrong password are one answer by design.
    if (error.apiError.code === "INVALID_CREDENTIALS") return "Identifiants incorrects.";
    if (error.apiError.code === "NETWORK") return error.apiError.message;
  }
  return "Connexion impossible pour le moment. Réessayez.";
}

export function LoginScreen() {
  const { state, login } = useAuth();
  const location = useLocation();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const from = (location.state as { from?: unknown } | null)?.from;

  if (state.status === "loading") return <SessionCheck />;
  if (state.status === "authenticated") {
    return <Navigate to={safeRedirectPath(from)} replace />;
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (pending) return;
    setPending(true);
    setError(null);
    try {
      await login(username, password);
    } catch (caught) {
      setError(errorSentence(caught));
      setPassword("");
      setPending(false);
    }
  }

  return (
    <div className={styles.center}>
      <form className={styles.card} onSubmit={onSubmit} aria-labelledby="login-title">
        <div className="u-stack-4">
          <h1 id="login-title" className="t-screen-title">
            Connexion à MCMA
          </h1>
          {state.status === "unauthenticated" && state.reason === "expired" ? (
            <p role="status" className={styles.notice}>
              {EXPIRED_MESSAGE}
            </p>
          ) : null}
          <div className={styles.field}>
            <label className={styles.label} htmlFor="login-username">
              Nom d'utilisateur
            </label>
            <input
              id="login-username"
              className={styles.input}
              type="text"
              autoComplete="username"
              autoCapitalize="none"
              spellCheck={false}
              required
              value={username}
              onChange={(e) => setUsername(e.target.value)}
            />
          </div>
          <div className={styles.field}>
            <label className={styles.label} htmlFor="login-password">
              Mot de passe
            </label>
            <input
              id="login-password"
              className={styles.input}
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>
          {error === null ? null : (
            <p role="alert" className={styles.error}>
              {error}
            </p>
          )}
          <Button type="submit" variant="primary" disabled={pending}>
            Se connecter
          </Button>
        </div>
      </form>
    </div>
  );
}
