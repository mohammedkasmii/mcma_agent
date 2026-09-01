import { describe, expect, it } from "vitest";
import { formatTimestamp } from "./datetime";

describe("formatTimestamp", () => {
  it("renders an ISO instant as readable French date and time", () => {
    const formatted = formatTimestamp("2026-01-15T09:30:00Z");
    expect(formatted).not.toBeNull();
    // Day/month/year with a time, not the raw ISO string.
    expect(formatted).toMatch(/^\d{2}\/\d{2}\/\d{4}/);
    expect(formatted).not.toContain("T");
    expect(formatted).not.toContain("Z");
  });

  it("keeps an absent timestamp absent rather than inventing one", () => {
    expect(formatTimestamp(null)).toBeNull();
    expect(formatTimestamp("")).toBeNull();
  });

  it("shows an unparseable value verbatim rather than a plausible date", () => {
    expect(formatTimestamp("pas-une-date")).toBe("pas-une-date");
  });

  it("does not alter the value it was given", () => {
    const original = "2026-01-15T09:30:00Z";
    formatTimestamp(original);
    expect(original).toBe("2026-01-15T09:30:00Z");
  });
});
