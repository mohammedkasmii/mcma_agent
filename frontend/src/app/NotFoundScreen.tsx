import { Link } from "react-router-dom";
import { ROUTES } from "@shared/utils/routes";

/**
 * An unknown address is a dead end, not an error to apologise for: say what
 * happened and offer the one route back.
 */
export function NotFoundScreen() {
  return (
    <div className="u-stack-4">
      <h1 className="t-screen-title">Page introuvable</h1>
      <p className="t-secondary">Cette adresse ne correspond à aucun écran de l'application.</p>
      <p>
        <Link to={ROUTES.overview}>Revenir à la vue d'ensemble</Link>
      </p>
    </div>
  );
}
