import type { Claim } from "@shared/types";

/**
 * Labels of the claim's active notifications the employee has not seen yet.
 * Deduplicated, like the category counts, so a malformed duplicate cannot
 * count twice.
 */
export function unreadCategories(claim: Claim): string[] {
  return [
    ...new Set(
      claim.notifications
        .filter((notification) => notification.unread)
        .map((notification) => notification.category),
    ),
  ];
}

export function hasUnreadNotification(claim: Claim): boolean {
  return claim.notifications.some((notification) => notification.unread);
}

/**
 * When the newest unopened notification on this dossier appeared, or null
 * when none of them carries a timestamp. Used to order the work queue so the
 * dossier that just arrived is the first one an employee sees.
 */
export function latestUnreadAppearance(claim: Claim): string | null {
  let latest: string | null = null;
  let latestInstant = Number.NEGATIVE_INFINITY;
  for (const notification of claim.notifications) {
    if (!notification.unread || notification.appearedAt === null) continue;
    // Compared as instants, not as text: "...Z" and "...+00:00" are the same
    // moment written two ways, and string order would disagree.
    const parsed = Date.parse(notification.appearedAt);
    const moment = Number.isNaN(parsed) ? Number.NEGATIVE_INFINITY : parsed;
    if (latest === null || moment > latestInstant) {
      latest = notification.appearedAt;
      latestInstant = moment;
    }
  }
  return latest;
}
