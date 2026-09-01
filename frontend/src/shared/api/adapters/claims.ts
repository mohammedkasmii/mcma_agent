import type { Claim, ClaimStatus } from "@shared/types";
import { CLAIM_STATUSES } from "@shared/types";
import { ApiRequestError } from "../client";
import { responseShapeError } from "../errors";

/**
 * The single wire-to-frontend mapping for claims.
 *
 * Pure: parsed body in, frontend records out, or it throws. No I/O.
 *
 * It validates rather than casts, and fails the whole read rather than
 * dropping or repairing a row. A claim silently omitted from the work queue
 * is a claim an employee never works, and a claim with a coerced status is
 * one whose tracking state is a guess.
 *
 * Null is preserved, never flattened to "". A portal claim genuinely without
 * an insured name is different from one whose name is an empty string, and
 * the interface renders those two cases differently.
 */

function fail(): never {
  throw new ApiRequestError(responseShapeError());
}

function requireRecord(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) fail();
  return value as Record<string, unknown>;
}

function requireString(value: unknown): string {
  if (typeof value !== "string" || value.length === 0) fail();
  return value;
}

function requireNullableString(value: unknown): string | null {
  if (value === null) return null;
  if (typeof value !== "string") fail();
  return value;
}

function requireInteger(value: unknown): number {
  if (typeof value !== "number" || !Number.isInteger(value)) fail();
  return value;
}

function requireStatus(value: unknown): ClaimStatus {
  const status = requireString(value);
  if (!(CLAIM_STATUSES as readonly string[]).includes(status)) fail();
  return status as ClaimStatus;
}

function requireCategories(value: unknown): string[] {
  if (!Array.isArray(value)) fail();
  return value.map((entry) => requireString(entry));
}

/** Maps one wire row. Exported for direct unit testing. */
export function toClaim(row: unknown): Claim {
  const wire = requireRecord(row);
  return {
    claimPk: requireString(wire["claim_pk"]),
    accountId: requireString(wire["account_id"]),
    portalClaimId: requireString(wire["portal_claim_id"]),
    reference: requireNullableString(wire["reference"]),
    insured: requireNullableString(wire["insured"]),
    police: requireNullableString(wire["police"]),
    matricule: requireNullableString(wire["matricule_norm"]),
    lastSeenVersion: requireInteger(wire["last_seen_version"]),
    accountEntity: requireString(wire["account_entity"]),
    accountScope: requireString(wire["account_scope"]),
    accountLabel: requireString(wire["account_label"]),
    status: requireStatus(wire["status"]),
    note: requireNullableString(wire["note"]),
    updatedAt: requireNullableString(wire["updated_at"]),
    categories: requireCategories(wire["categories"]),
  };
}

/**
 * Maps the GET /claims envelope for one account.
 *
 * `expectedAccountId` is the account the request was scoped to. A row
 * carrying a different account_id fails the whole read instead of being
 * rendered: the work queue is presented as one account's work, and showing a
 * row from elsewhere under that heading is the specific confusion this
 * product cannot afford.
 *
 * This is a display-integrity check, not an authorization one. The backend
 * already filters rows by account access on every request and remains the
 * authority; this only refuses to draw something the interface would be
 * describing untruthfully.
 */
export function toClaims(body: unknown, expectedAccountId: string): Claim[] {
  const envelope = requireRecord(body);
  const rows = envelope["claims"];
  if (!Array.isArray(rows)) fail();

  const claims = rows.map(toClaim);
  if (claims.some((claim) => claim.accountId !== expectedAccountId)) fail();
  return claims;
}
