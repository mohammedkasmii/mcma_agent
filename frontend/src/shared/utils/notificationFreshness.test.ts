import { describe, expect, it } from "vitest";
import { toClaim } from "@shared/api/adapters/claims";
import { CLAIM_NEW_WIRE, CLAIM_TRACKED_WIRE } from "../../test/fixtures";
import { hasUnreadNotification, unreadCategories } from "./notificationFreshness";

const note = (category: string, unread: boolean) => ({
  category,
  unread,
  appeared_at: null,
  seen_at: null,
});

describe("notification freshness helpers", () => {
  it("lists only the unread categories, once each", () => {
    const claim = toClaim({
      ...CLAIM_NEW_WIRE,
      notifications: [note("A", true), note("B", false), note("A", true)],
    });
    expect(unreadCategories(claim)).toEqual(["A"]);
    expect(hasUnreadNotification(claim)).toBe(true);
  });

  it("reports nothing new when every notification is seen or there are none", () => {
    expect(hasUnreadNotification(toClaim(CLAIM_NEW_WIRE))).toBe(false);
    expect(unreadCategories(toClaim(CLAIM_TRACKED_WIRE))).toEqual([]);
  });
});
