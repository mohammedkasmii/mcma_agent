import type { ConnectionState, PortalAccount, PortalEntity } from "@shared/types";
import { ApiRequestError } from "../client";
import { responseShapeError } from "../errors";

/**
 * The single wire-to-frontend mapping for portal accounts.
 *
 * Pure: it takes an already-parsed response body and returns frontend
 * records, or throws. It performs no I/O, so it is testable against fixed
 * bodies without a network.
 *
 * It validates rather than casts. A field that is missing, mistyped, or
 * carries a value this frontend does not understand fails the whole read
 * instead of producing a partially-understood account list — an account
 * silently dropped from the rail is an account an employee stops working,
 * and a half-mapped account is one whose capability cannot be trusted.
 */

const ENTITIES: readonly string[] = ["MCMA", "MAMDA"];
const CONNECTION_STATES: readonly string[] = [
  "CONNECTED",
  "RECONNECT_REQUIRED",
  "NOT_CONNECTED",
];

function fail(): never {
  throw new ApiRequestError(responseShapeError());
}

function requireString(value: unknown): string {
  if (typeof value !== "string" || value.length === 0) fail();
  return value;
}

function requireBoolean(value: unknown): boolean {
  if (typeof value !== "boolean") fail();
  return value;
}

function requireRecord(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) fail();
  return value as Record<string, unknown>;
}

/** Maps one wire row. Exported for direct unit testing. */
export function toPortalAccount(row: unknown): PortalAccount {
  const wire = requireRecord(row);

  const entity = requireString(wire["entity"]);
  if (!ENTITIES.includes(entity)) fail();

  const connectionState = requireString(wire["connection_state"]);
  if (!CONNECTION_STATES.includes(connectionState)) fail();

  return {
    accountId: requireString(wire["account_id"]),
    label: requireString(wire["label"]),
    entity: entity as PortalEntity,
    scope: requireString(wire["scope"]),
    connectionState: connectionState as ConnectionState,
    sessionActive: requireBoolean(wire["session_active"]),
    // Read, never inferred. The backend decides which accounts may be the
    // target of an automation; `entity === "MCMA"` is not an authorization
    // rule this frontend is allowed to reimplement.
    writable: requireBoolean(wire["writable"]),
  };
}

/** Maps the GET /accounts envelope. */
export function toPortalAccounts(body: unknown): PortalAccount[] {
  const envelope = requireRecord(body);
  const rows = envelope["accounts"];
  if (!Array.isArray(rows)) fail();
  return rows.map(toPortalAccount);
}
