import type { UserRole } from "@shared/types";

export const ROLE_LABELS: Record<UserRole, string> = {
  admin: "Administrateur",
  operator: "Opérateur",
  viewer: "Lecteur",
};

export const ROLE_DESCRIPTIONS: Record<UserRole, string> = {
  admin: "gère les utilisateurs de la plateforme et dispose de tous les accès.",
  operator: "travaille avec les notifications et les actions opérationnelles.",
  viewer: "consulte les informations sans effectuer d'actions modifiant les données.",
};

export const ROLE_ORDER: readonly UserRole[] = ["admin", "operator", "viewer"];

export function roleLabel(role: UserRole): string {
  return ROLE_LABELS[role];
}
