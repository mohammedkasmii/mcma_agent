import type { OwnRunnerStatusInfo, RunnerOverview } from "@shared/types";
import { apiGet, apiSend } from "./client";
import { toEnrollmentCreated, toOwnRunnerStatus, toRunnerOverview } from "./adapters/runners";

/** API paths. The SPA page lives elsewhere (ROUTES.adminRunners). */
export const ADMIN_RUNNERS_PATH = "/admin/runners";
export const ADMIN_ENROLLMENTS_PATH = "/admin/runner-enrollments";
export const RUNNER_STATUS_PATH = "/runner-status";

export async function fetchRunnerOverview(signal?: AbortSignal): Promise<RunnerOverview> {
  return toRunnerOverview(await apiGet(ADMIN_RUNNERS_PATH, signal));
}

export async function fetchOwnRunnerStatus(signal?: AbortSignal): Promise<OwnRunnerStatusInfo> {
  return toOwnRunnerStatus(await apiGet(RUNNER_STATUS_PATH, signal));
}

/** The returned pairing code exists only in this response; the caller must not cache it. */
export async function createEnrollment(input: {
  readonly targetUserId: string;
  readonly runnerLabel?: string;
}) {
  return toEnrollmentCreated(
    await apiSend(ADMIN_ENROLLMENTS_PATH, "POST", {
      target_user_id: input.targetUserId,
      ...(input.runnerLabel === undefined ? {} : { runner_label: input.runnerLabel }),
    }),
  );
}

export async function revokeRunner(runnerId: string): Promise<void> {
  await apiSend(`${ADMIN_RUNNERS_PATH}/${encodeURIComponent(runnerId)}/revoke`, "POST");
}
