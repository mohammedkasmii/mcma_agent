import type { Claim } from "@shared/types";
import { hasUnreadNotification, latestUnreadAppearance } from "@shared/utils/notificationFreshness";

/**
 * The order an employee actually works in: what arrived and has not been
 * opened, newest first.
 *
 * Deliberately a pure comparator over a COPY. The array handed in belongs to
 * the TanStack Query cache, and sorting it in place would reorder every other
 * reader of that same cached list — including the detail screen resolving a
 * claim from it — while React saw no state change at all.
 *
 * Ties break on stable identity (reference, then the opaque key) rather than
 * on arrival order, so two renders of the same data always produce the same
 * order even if the backend returned the rows differently.
 */

function instant(value: string | null): number {
  if (value === null) return 0;
  const parsed = Date.parse(value);
  // An unparseable timestamp sorts oldest rather than throwing: a row the
  // employee can still read is better than a queue that fails to render.
  return Number.isNaN(parsed) ? 0 : parsed;
}

function tieBreak(left: Claim, right: Claim): number {
  const byReference = (left.reference ?? "").localeCompare(right.reference ?? "", "fr");
  return byReference !== 0 ? byReference : left.claimPk.localeCompare(right.claimPk);
}

export function compareQueueOrder(left: Claim, right: Claim): number {
  const leftUnread = hasUnreadNotification(left);
  const rightUnread = hasUnreadNotification(right);
  if (leftUnread !== rightUnread) return leftUnread ? -1 : 1;

  if (leftUnread && rightUnread) {
    // Newest appearance first, among dossiers that are both new.
    const byAppearance = instant(latestUnreadAppearance(right)) - instant(latestUnreadAppearance(left));
    if (byAppearance !== 0) return byAppearance;
  }

  return tieBreak(left, right);
}

/** A new array. The input is never mutated. */
export function orderedQueue(claims: readonly Claim[]): Claim[] {
  return [...claims].sort(compareQueueOrder);
}
