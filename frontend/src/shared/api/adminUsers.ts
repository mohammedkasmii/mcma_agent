import type { PlatformUser, UserRole } from "@shared/types";
import { apiGet, apiSend } from "./client";
import { toPlatformUser, toPlatformUsers } from "./adapters/auth";

export const ADMIN_USERS_PATH = "/admin/users";

export interface NewUserInput {
  readonly username: string;
  readonly password: string;
  readonly role: UserRole;
  readonly accountIds: readonly string[];
}

export interface UserPatch {
  readonly active?: boolean;
  readonly role?: UserRole;
  readonly accountIds?: readonly string[];
}

export async function fetchUsers(signal?: AbortSignal): Promise<PlatformUser[]> {
  return toPlatformUsers(await apiGet(ADMIN_USERS_PATH, signal));
}

export async function createUser(input: NewUserInput): Promise<PlatformUser> {
  return toPlatformUser(
    await apiSend(ADMIN_USERS_PATH, "POST", {
      username: input.username,
      password: input.password,
      role: input.role,
      account_ids: input.accountIds,
    }),
  );
}

export async function updateUser(userId: string, patch: UserPatch): Promise<PlatformUser> {
  const body: Record<string, unknown> = {};
  if (patch.active !== undefined) body["active"] = patch.active;
  if (patch.role !== undefined) body["role"] = patch.role;
  if (patch.accountIds !== undefined) body["account_ids"] = patch.accountIds;
  return toPlatformUser(
    await apiSend(`${ADMIN_USERS_PATH}/${encodeURIComponent(userId)}`, "PATCH", body),
  );
}

export async function resetUserPassword(userId: string, password: string): Promise<void> {
  await apiSend(`${ADMIN_USERS_PATH}/${encodeURIComponent(userId)}/password`, "POST", { password });
}
