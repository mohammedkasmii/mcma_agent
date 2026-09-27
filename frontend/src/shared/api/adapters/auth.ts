import type { AuthSession, PlatformUser, UserRole } from "@shared/types";
import { ApiRequestError } from "../client";
import { responseShapeError } from "../errors";

/** Wire-to-frontend mapping for /auth/me and /admin/users. Validates, never casts. */

const ROLES: readonly string[] = ["admin", "operator", "viewer"];

function fail(): never {
  throw new ApiRequestError(responseShapeError());
}

function record(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) fail();
  return value as Record<string, unknown>;
}

function str(value: unknown): string {
  if (typeof value !== "string" || value.length === 0) fail();
  return value;
}

function role(value: unknown): UserRole {
  if (typeof value !== "string" || !ROLES.includes(value)) fail();
  return value as UserRole;
}

function strings(value: unknown): string[] {
  if (!Array.isArray(value)) fail();
  return value.map(str);
}

export function toAuthSession(body: unknown): AuthSession {
  const row = record(body);
  if (typeof row["local_single_user"] !== "boolean") fail();
  return {
    userId: str(row["user_id"]),
    username: str(row["username"]),
    role: role(row["role"]),
    permissions: strings(row["permissions"]),
    accountIds: strings(row["account_ids"]),
    localSingleUser: row["local_single_user"],
  };
}

function toUser(value: unknown): PlatformUser {
  const row = record(value);
  if (typeof row["active"] !== "boolean") fail();
  return {
    userId: str(row["user_id"]),
    username: str(row["username"]),
    role: role(row["role"]),
    active: row["active"],
    accountIds: strings(row["account_ids"]),
  };
}

export function toPlatformUsers(body: unknown): PlatformUser[] {
  const users = record(body)["users"];
  if (!Array.isArray(users)) fail();
  return users.map(toUser);
}

export function toPlatformUser(body: unknown): PlatformUser {
  return toUser(record(body)["user"]);
}
