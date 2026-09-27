import type {
  EligibleEmployee,
  OwnRunnerStatus,
  OwnRunnerStatusInfo,
  PendingEnrollment,
  Runner,
  RunnerOverview,
  RunnerSession,
  RunnerStatus,
  SessionState,
} from "@shared/types";
import { ApiRequestError } from "../client";
import { responseShapeError } from "../errors";

/**
 * Wire-to-frontend mapping for runners. Validates rather than casts. Nothing
 * secret is read: only fields the contract lists are picked, so an unexpected
 * digest or token in a body could never reach a component.
 */

const STATUSES: readonly string[] = ["ONLINE", "OFFLINE", "REVOKED"];
const OWN_STATUSES: readonly string[] = ["UNPAIRED", ...STATUSES];
const SESSION_STATES: readonly string[] = ["NOT_CONFIGURED", "LOGIN_REQUIRED", "READY", "ERROR"];

function fail(): never {
  throw new ApiRequestError(responseShapeError());
}

function rec(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) fail();
  return value as Record<string, unknown>;
}

function str(value: unknown): string {
  if (typeof value !== "string" || value.length === 0) fail();
  return value;
}

function strOrNull(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  return str(value);
}

function numOrNull(value: unknown): number | null {
  if (value === null || value === undefined) return null;
  if (typeof value !== "number") fail();
  return value;
}

function list(value: unknown): unknown[] {
  if (!Array.isArray(value)) fail();
  return value;
}

function oneOf<T extends string>(value: unknown, allowed: readonly string[]): T {
  if (typeof value !== "string" || !allowed.includes(value)) fail();
  return value as T;
}

function toSession(value: unknown): RunnerSession {
  const row = rec(value);
  return {
    accountId: str(row["account_id"]),
    state: oneOf<SessionState>(row["state"], SESSION_STATES),
  };
}

export function toRunner(value: unknown): Runner {
  const row = rec(value);
  return {
    runnerId: str(row["runner_id"]),
    userId: str(row["user_id"]),
    username: str(row["username"]),
    runnerLabel: strOrNull(row["runner_label"]),
    status: oneOf<RunnerStatus>(row["status"], STATUSES),
    lastSeenAt: strOrNull(row["last_seen_at"]),
    createdAt: str(row["created_at"]),
    revokedAt: strOrNull(row["revoked_at"]),
    appVersion: strOrNull(row["app_version"]),
    protocolVersion: numOrNull(row["protocol_version"]),
    sessions: list(row["sessions"]).map(toSession),
  };
}

export function toEnrollment(value: unknown): PendingEnrollment {
  const row = rec(value);
  return {
    enrollmentId: str(row["enrollment_id"]),
    targetUserId: str(row["target_user_id"]),
    targetUsername: str(row["target_username"]),
    runnerLabel: strOrNull(row["runner_label"]),
    expiresAt: str(row["expires_at"]),
  };
}

function toEmployee(value: unknown): EligibleEmployee {
  const row = rec(value);
  return { userId: str(row["user_id"]), username: str(row["username"]) };
}

export function toRunnerOverview(body: unknown): RunnerOverview {
  const row = rec(body);
  return {
    runners: list(row["runners"]).map(toRunner),
    pendingEnrollments: list(row["pending_enrollments"]).map(toEnrollment),
    eligibleEmployees: list(row["eligible_employees"]).map(toEmployee),
  };
}

/** POST /admin/runner-enrollments: the pairing code is returned only here. */
export function toEnrollmentCreated(body: unknown): {
  enrollment: PendingEnrollment;
  pairingCode: string;
} {
  const row = rec(body);
  return { enrollment: toEnrollment(row["enrollment"]), pairingCode: str(row["pairing_code"]) };
}

export function toOwnRunnerStatus(body: unknown): OwnRunnerStatusInfo {
  const row = rec(body);
  return {
    status: oneOf<OwnRunnerStatus>(row["status"], OWN_STATUSES),
    runnerLabel: strOrNull(row["runner_label"]),
    lastSeenAt: strOrNull(row["last_seen_at"]),
    sessions: list(row["sessions"]).map(toSession),
  };
}
