/**
 * One vocabulary for notification volume, shared by the rail, the overview
 * and the work queue.
 *
 * Two different numbers describe the same alert load and the employee needs
 * both: a notification is one category membership (what the portal's own
 * notification bar counts), while a dossier is one claim. A dossier flagged
 * in two categories is two notifications and one dossier — saying only
 * "2 nouvelles" made people look for a second file that does not exist.
 *
 * Centralised so the three surfaces can never word the same fact differently.
 *
 * French agreement: only counts ABOVE one take the plural -- "0 nouvelle
 * notification", "1 nouvelle notification", "2 nouvelles notifications".
 */

function plural(count: number): boolean {
  return count > 1;
}

export function newNotificationsLabel(count: number): string {
  return `${count} ${plural(count) ? "nouvelles notifications" : "nouvelle notification"}`;
}

export function concernedDossiersLabel(count: number): string {
  return `${count} ${plural(count) ? "dossiers concernés" : "dossier concerné"}`;
}

export function activeNotificationsLabel(count: number): string {
  return `${count} ${plural(count) ? "notifications actives" : "notification active"}`;
}

/** The single sentence a screen reader hears for an account's alert load. */
export function unreadSummarySentence(notifications: number, dossiers: number): string {
  return `${newNotificationsLabel(notifications)}, ${concernedDossiersLabel(dossiers)}`;
}
