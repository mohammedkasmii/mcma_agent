import type {
  ConnectionState,
  PollAttemptStatus,
  PortalAccount,
  PortalEntity,
} from "@shared/types";
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
  "UNVERIFIED",
  "CONNECTED",
  "RECONNECT_REQUIRED",
  "NOT_CONNECTED",
];

const POLL_ATTEMPT_STATUSES: readonly string[] = ["COMPLETE", "PARTIAL", "FAILED"];

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

/**
 * A count the employee is shown. A negative or fractional "number of new
 * notifications" is not a count this frontend will render, and a missing one
 * must not silently become 0 -- a badge that says nothing is new is exactly
 * the failure an employee cannot detect.
 */
function requireCount(value: unknown): number {
  if (typeof value !== "number" || !Number.isInteger(value) || value < 0) fail();
  return value;
}

/** An optional timestamp. Null means "never happened", never "unknown". */
function requireNullableString(value: unknown): string | null {
  if (value === null) return null;
  if (typeof value !== "string" || value.length === 0) fail();
  return value;
}

function requireNullableAttemptStatus(value: unknown): PollAttemptStatus | null {
  if (value === null) return null;
  const status = requireString(value);
  if (!POLL_ATTEMPT_STATUSES.includes(status)) fail();
  return status as PollAttemptStatus;
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
    // Counts and poll state are derived server-side from the same rows the
    // work queue reads. The frontend re-derives none of them: a second
    // definition of "new" is how two screens start disagreeing.
    activeNotificationCount: requireCount(wire["active_notification_count"]),
    unreadNotificationCount: requireCount(wire["unread_notification_count"]),
    unreadClaimCount: requireCount(wire["unread_claim_count"]),
    notificationLastAttemptAt: requireNullableString(wire["notification_last_attempt_at"]),
    notificationLastAttemptStatus: requireNullableAttemptStatus(
      wire["notification_last_attempt_status"],
    ),
    notificationLastSuccessAt: requireNullableString(wire["notification_last_success_at"]),
  };
}

/** Maps the GET /accounts envelope. */
export function toPortalAccounts(body: unknown): PortalAccount[] {
  const envelope = requireRecord(body);
  const rows = envelope["accounts"];
  if (!Array.isArray(rows)) fail();
  return rows.map(toPortalAccount);
}

/**
 * The result of a manual notification refresh.
 *
 * `message` is the backend's own employee-facing sentence, taken from its
 * fixed _REFRESH_MESSAGES allowlist. It is length-bounded here anyway: a
 * sentence this frontend renders should never be able to grow into a page of
 * portal text if that allowlist ever changed.
 */
export interface RefreshOutcome {
  readonly outcome: string;
  readonly message: string;
}

const REFRESH_MESSAGE_MAX = 200;

export function toRefreshOutcome(body: unknown): RefreshOutcome {
  if (typeof body !== "object" || body === null || Array.isArray(body)) fail();
  const record = body as Record<string, unknown>;
  const outcome = record["outcome"];
  const message = record["message"];
  if (typeof outcome !== "string" || outcome.length === 0) fail();
  return {
    outcome,
    message:
      typeof message === "string" && message.length > 0 && message.length <= REFRESH_MESSAGE_MAX
        ? message
        : "Actualisation terminée.",
  };
}

/** Central-mode notification onboarding (async login on the employee's workstation). */
export const LOGIN_STATES = [
  "IDLE",
  "QUEUED",
  "OPENING_WINDOW",
  "WINDOW_OPENED",
  "WAITING_FOR_LOGIN",
  "SUCCEEDED",
  "FAILED",
  "CANCELLED",
  "EXPIRED",
] as const;
export type LoginState = (typeof LOGIN_STATES)[number];

export interface LoginStatus {
  readonly accountId: string;
  readonly requestId: string | null;
  readonly state: LoginState;
  readonly outcomeCode: string | null;
}

/** Only these states mean work is still in flight and polling is justified. */
export function isLoginActive(state: LoginState | undefined): boolean {
  return state === "QUEUED" || state === "OPENING_WINDOW" || state === "WINDOW_OPENED" || state === "WAITING_FOR_LOGIN";
}

/** True when a POST /login answer is the async onboarding view (it carries `state`). */
export function isOnboardingBody(body: unknown): boolean {
  return typeof body === "object" && body !== null && !Array.isArray(body) && "state" in body;
}

export function toLoginStatus(body: unknown): LoginStatus {
  if (typeof body !== "object" || body === null || Array.isArray(body)) fail();
  const record = body as Record<string, unknown>;
  const state = record["state"];
  const accountId = record["account_id"];
  const requestId = record["request_id"];
  const outcome = record["outcome_code"];
  if (typeof state !== "string" || !(LOGIN_STATES as readonly string[]).includes(state)) fail();
  if (typeof accountId !== "string" || accountId.length === 0 || accountId.length > 64) fail();
  if (requestId !== null && (typeof requestId !== "string" || requestId.length > 64)) fail();
  if (outcome !== null && (typeof outcome !== "string" || outcome.length === 0 || outcome.length > 64)) fail();
  return { accountId, requestId, state: state as LoginState, outcomeCode: outcome };
}
