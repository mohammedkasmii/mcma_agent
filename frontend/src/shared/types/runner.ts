export type RunnerStatus = "ONLINE" | "OFFLINE" | "REVOKED";
export type OwnRunnerStatus = "UNPAIRED" | RunnerStatus;
export type SessionState = "NOT_CONFIGURED" | "LOGIN_REQUIRED" | "READY" | "ERROR";

export interface RunnerSession {
  readonly accountId: string;
  readonly state: SessionState;
}

export interface Runner {
  readonly runnerId: string;
  readonly userId: string;
  readonly username: string;
  readonly runnerLabel: string | null;
  readonly status: RunnerStatus;
  readonly lastSeenAt: string | null;
  readonly createdAt: string;
  readonly revokedAt: string | null;
  readonly appVersion: string | null;
  readonly protocolVersion: number | null;
  readonly sessions: readonly RunnerSession[];
}

export interface PendingEnrollment {
  readonly enrollmentId: string;
  readonly targetUserId: string;
  readonly targetUsername: string;
  readonly runnerLabel: string | null;
  readonly expiresAt: string;
}

export interface EligibleEmployee {
  readonly userId: string;
  readonly username: string;
}

export interface RunnerOverview {
  readonly runners: readonly Runner[];
  readonly pendingEnrollments: readonly PendingEnrollment[];
  readonly eligibleEmployees: readonly EligibleEmployee[];
}

export interface OwnRunnerStatusInfo {
  readonly status: OwnRunnerStatus;
  readonly runnerLabel: string | null;
  readonly lastSeenAt: string | null;
  readonly sessions: readonly RunnerSession[];
}
