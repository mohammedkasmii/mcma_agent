import type { ReactNode } from "react";
import { Navigate, Outlet, useLocation } from "react-router-dom";
import { ROUTES } from "@shared/utils/routes";
import { Button } from "@shared/ui";
import { useAuth } from "./AuthProvider";
import styles from "./Auth.module.css";

export function SessionCheck() {
  return (
    <div className={styles.center}>
      <p role="status" className="t-secondary">
        Vérification de la session…
      </p>
    </div>
  );
}

/**
 * Layout route: children (the shell, its queries and its event stream) mount
 * only once authentication is confirmed.
 */
export function RequireAuth() {
  const { state, retry } = useAuth();
  const location = useLocation();

  if (state.status === "loading") return <SessionCheck />;
  if (state.status === "unavailable") {
    return (
      <div className={styles.center}>
        <div className="u-stack-4">
          <p role="alert">Le serveur est injoignable. Vérifiez votre connexion.</p>
          <Button onClick={retry}>Réessayer</Button>
        </div>
      </div>
    );
  }
  if (state.status === "unauthenticated") {
    const from = `${location.pathname}${location.search}`;
    return (
      <Navigate to={ROUTES.login} replace state={state.reason === "logout" ? null : { from }} />
    );
  }
  return <Outlet />;
}

/** Admin-only guard inside the shell. Non-admins never fire an admin request. */
export function RequireAdmin({ children }: { readonly children: ReactNode }) {
  const { state } = useAuth();
  if (state.status !== "authenticated" || state.session.role !== "admin") {
    return (
      <div className="u-stack-4">
        <h1 className="t-screen-title">Accès refusé</h1>
        <p role="alert">Accès réservé aux administrateurs.</p>
      </div>
    );
  }
  return <>{children}</>;
}
