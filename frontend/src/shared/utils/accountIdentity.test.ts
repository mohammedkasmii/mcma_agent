import { describe, expect, it } from "vitest";
import {
  capabilityLabel,
  connectionLabel,
  connectionMarker,
  formatAccountIdentity,
} from "./accountIdentity";

describe("formatAccountIdentity", () => {
  it("reads as entity then scope", () => {
    expect(formatAccountIdentity({ entity: "MCMA", scope: "ZONE-A" })).toBe("MCMA • ZONE-A");
  });

  it("normalises scope casing", () => {
    expect(formatAccountIdentity({ entity: "MAMDA", scope: "zone-b" })).toBe("MAMDA • ZONE-B");
  });
});

describe("connection state", () => {
  it("labels every state", () => {
    expect(connectionLabel("CONNECTED")).toBe("Connecté");
    expect(connectionLabel("RECONNECT_REQUIRED")).toBe("Reconnexion requise");
    expect(connectionLabel("NOT_CONNECTED")).toBe("Non connecté");
  });

  it("gives every state a distinct marker shape so colour is never the only signal", () => {
    const markers = [
      connectionMarker("CONNECTED"),
      connectionMarker("RECONNECT_REQUIRED"),
      connectionMarker("NOT_CONNECTED"),
    ];
    expect(new Set(markers).size).toBe(markers.length);
  });
});

describe("capabilityLabel", () => {
  it("follows the backend writable flag rather than the entity name", () => {
    expect(capabilityLabel({ writable: true })).toBe("Automatisation autorisée");
    expect(capabilityLabel({ writable: false })).toBe("Lecture seule");
  });
});
