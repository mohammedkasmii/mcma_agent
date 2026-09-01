import { describe, expect, it } from "vitest";
import { CLAIM_STATUSES } from "@shared/types";
import { claimStatusLabel, claimStatusTone } from "./claimStatus";

describe("claimStatusLabel", () => {
  it("uses the fixed employee-facing wording", () => {
    expect(claimStatusLabel("NEW")).toBe("À traiter");
    expect(claimStatusLabel("IN_PROGRESS")).toBe("En cours");
    expect(claimStatusLabel("WAITING")).toBe("En attente");
    expect(claimStatusLabel("DONE")).toBe("Traité");
    expect(claimStatusLabel("NOT_APPLICABLE")).toBe("Sans suite");
  });

  it("covers exactly the five backend statuses", () => {
    expect(CLAIM_STATUSES).toHaveLength(5);
    const labels = CLAIM_STATUSES.map(claimStatusLabel);
    expect(new Set(labels).size).toBe(5);
    expect(labels).not.toContain("TODO");
  });
});

describe("claimStatusTone", () => {
  it("gives every status a tone without making colour the only signal", () => {
    // Each status has a tone, and each also has a distinct label above.
    for (const status of CLAIM_STATUSES) {
      expect(claimStatusTone(status).length).toBeGreaterThan(0);
    }
  });
});
