export type UserRole = "admin" | "operator" | "viewer";

export interface AuthSession {
  readonly userId: string;
  readonly username: string;
  readonly role: UserRole;
  readonly permissions: readonly string[];
  readonly accountIds: readonly string[];
  /** True only on the single-office Windows install (auto-authenticated loopback user). */
  readonly localSingleUser: boolean;
}

export interface PlatformUser {
  readonly userId: string;
  readonly username: string;
  readonly role: UserRole;
  readonly active: boolean;
  readonly accountIds: readonly string[];
}
