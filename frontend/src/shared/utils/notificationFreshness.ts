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
