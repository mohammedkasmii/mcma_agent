import { describe, expect, it } from "vitest";
import type { Claim } from "@shared/types";
import { toClaim } from "@shared/api/adapters/claims";
import { CLAIM_NEW_WIRE } from "../../test/fixtures";
import { compareQueueOrder, orderedQueue } from "./ordering";

/**
 * Queue order is what an employee works down, so it is asserted as an exact
 * sequence rather than as "contains".
 */

function claim(
  reference: string,
  notifications: readonly { unread: boolean; appearedAt: string | null }[],
): Claim {
  return toClaim({
    ...CLAIM_NEW_WIRE,
    claim_pk: `pk-${reference}`,
    reference,
    categories: notifications.map((_unused, index) => `Catégorie ${index}`),
    notifications: notifications.map((notification, index) => ({
      category: `Catégorie ${index}`,
      unread: notification.unread,
      appeared_at: notification.appearedAt,
      seen_at: null,
    })),
  });
}

const seen = (reference: string) => claim(reference, [{ unread: false, appearedAt: null }]);
const unreadAt = (reference: string, appearedAt: string | null) =>
  claim(reference, [{ unread: true, appearedAt }]);

const references = (claims: readonly Claim[]) => claims.map((entry) => entry.reference);

describe("queue ordering", () => {
  it("puts dossiers with unread notifications before seen ones", () => {
    const queue = orderedQueue([
      seen("SEEN-1"),
      unreadAt("NEW-1", "2026-02-01T08:00:00Z"),
      seen("SEEN-2"),
    ]);
    expect(references(queue)).toEqual(["NEW-1", "SEEN-1", "SEEN-2"]);
  });

  it("orders unread dossiers newest appearance first", () => {
    const queue = orderedQueue([
      unreadAt("OLD", "2026-02-01T08:00:00Z"),
      unreadAt("NEWEST", "2026-02-03T08:00:00Z"),
      unreadAt("MIDDLE", "2026-02-02T08:00:00Z"),
    ]);
    expect(references(queue)).toEqual(["NEWEST", "MIDDLE", "OLD"]);
  });

  it("uses the newest unread notification when a dossier has several", () => {
    const older = claim("OLDER", [
      { unread: true, appearedAt: "2026-02-01T08:00:00Z" },
      { unread: true, appearedAt: "2026-02-01T09:00:00Z" },
    ]);
    const newer = claim("NEWER", [
      { unread: true, appearedAt: "2026-02-01T10:00:00Z" },
      // A seen notification is not what makes this dossier new, so its own
      // timestamp must not be used for ordering.
      { unread: false, appearedAt: "2026-03-01T10:00:00Z" },
    ]);
    expect(references(orderedQueue([older, newer]))).toEqual(["NEWER", "OLDER"]);
  });

  it("treats the same instant written two ways as equal", () => {
    const zulu = unreadAt("ZULU", "2026-02-01T08:00:00Z");
    const offset = unreadAt("OFFSET", "2026-02-01T08:00:00+00:00");
    // Neither is newer, so the deterministic tie-break decides.
    expect(references(orderedQueue([zulu, offset]))).toEqual(["OFFSET", "ZULU"]);
  });

  it("breaks ties deterministically, whatever order the backend sent", () => {
    const sameMoment = "2026-02-01T08:00:00Z";
    const forward = orderedQueue([
      unreadAt("B", sameMoment),
      unreadAt("A", sameMoment),
      unreadAt("C", sameMoment),
    ]);
    const reversed = orderedQueue([
      unreadAt("C", sameMoment),
      unreadAt("A", sameMoment),
      unreadAt("B", sameMoment),
    ]);
    expect(references(forward)).toEqual(["A", "B", "C"]);
    expect(references(reversed)).toEqual(references(forward));
  });

  it("orders seen dossiers deterministically too", () => {
    expect(references(orderedQueue([seen("C"), seen("A"), seen("B")]))).toEqual(["A", "B", "C"]);
  });

  it("keeps an unread dossier with no timestamp ahead of every seen one", () => {
    const queue = orderedQueue([
      seen("SEEN"),
      unreadAt("NO-DATE", null),
      unreadAt("DATED", "2026-02-01T08:00:00Z"),
    ]);
    expect(references(queue)).toEqual(["DATED", "NO-DATE", "SEEN"]);
  });

  it("does not drop a dossier whose timestamp cannot be parsed", () => {
    const queue = orderedQueue([seen("SEEN"), unreadAt("BROKEN", "pas une date")]);
    expect(references(queue)).toEqual(["BROKEN", "SEEN"]);
  });

  it("never mutates or reuses the array it was given", () => {
    // The input belongs to the TanStack Query cache: sorting it in place
    // would silently reorder every other reader of that same list.
    const input = [seen("SEEN"), unreadAt("NEW", "2026-02-01T08:00:00Z")];
    const snapshot = references(input);
    const queue = orderedQueue(input);

    expect(references(input)).toEqual(snapshot);
    expect(queue).not.toBe(input);
  });

  it("is a consistent comparator", () => {
    const left = unreadAt("A", "2026-02-02T08:00:00Z");
    const right = unreadAt("B", "2026-02-01T08:00:00Z");
    expect(compareQueueOrder(left, right)).toBeLessThan(0);
    expect(compareQueueOrder(right, left)).toBeGreaterThan(0);
    expect(compareQueueOrder(left, left)).toBe(0);
  });
});
