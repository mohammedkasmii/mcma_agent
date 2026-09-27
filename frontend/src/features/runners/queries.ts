import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createEnrollment, fetchOwnRunnerStatus, fetchRunnerOverview, revokeRunner } from "@shared/api/runners";

/** Distinct prefixes: SSE invalidation never reaches these. */
export const ADMIN_RUNNERS_QUERY_KEY = ["admin", "runners"] as const;
export const RUNNER_STATUS_QUERY_KEY = ["runner-status"] as const;

/** Only mounted on the admin page, so polling stops when it unmounts. */
export const ADMIN_RUNNERS_POLL_MS = 10_000;
export const RUNNER_STATUS_POLL_MS = 15_000;

export function useRunnerOverviewQuery() {
  return useQuery({
    queryKey: ADMIN_RUNNERS_QUERY_KEY,
    queryFn: ({ signal }) => fetchRunnerOverview(signal),
    refetchInterval: ADMIN_RUNNERS_POLL_MS,
  });
}

export function useOwnRunnerStatusQuery() {
  return useQuery({
    queryKey: RUNNER_STATUS_QUERY_KEY,
    queryFn: ({ signal }) => fetchOwnRunnerStatus(signal),
    refetchInterval: RUNNER_STATUS_POLL_MS,
    // Cheap refetch every time the panel mounts, whatever the cache holds.
    staleTime: 0,
    refetchOnMount: "always",
  });
}

/**
 * The mutation returns only the enrollment summary. The pairing code is handed
 * to `onCode` (component state) from inside the mutation function, so it never
 * enters the mutation cache as data or variables.
 */
export function useCreateEnrollment(onCode: (code: string) => void) {
  const queryClient = useQueryClient();
  return useMutation({
    gcTime: 0,
    mutationFn: async (input: { readonly targetUserId: string; readonly runnerLabel?: string }) => {
      const created = await createEnrollment(input);
      onCode(created.pairingCode);
      return created.enrollment;
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ADMIN_RUNNERS_QUERY_KEY }),
  });
}

export function useRevokeRunner() {
  const queryClient = useQueryClient();
  return useMutation({
    gcTime: 0,
    mutationFn: (runnerId: string) => revokeRunner(runnerId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ADMIN_RUNNERS_QUERY_KEY }),
  });
}
