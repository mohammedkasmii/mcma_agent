import { useQuery } from "@tanstack/react-query";
import type { UseQueryResult } from "@tanstack/react-query";
import type { Job } from "@shared/types";
import { fetchJobs } from "@shared/api/jobs";

/**
 * The global job collection.
 *
 * GET /jobs with no filter returns the jobs of every account the employee can
 * see; the backend does the row filtering. This is the source for the active
 * run surface in the shell, and it is a separate cache entry from the
 * per-account job details — those keep their own account-scoped keys and
 * their own account cross-check.
 */
export const GLOBAL_JOBS_QUERY_KEY = ["jobs", "global"] as const;

export function useGlobalJobsQuery(): UseQueryResult<Job[], Error> {
  return useQuery({
    queryKey: GLOBAL_JOBS_QUERY_KEY,
    queryFn: ({ signal }) => fetchJobs(signal),
  });
}
