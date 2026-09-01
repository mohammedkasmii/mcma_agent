import { useMemo } from "react";
import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

/**
 * Server-state defaults for an operations console.
 *
 * `refetchOnWindowFocus` is off and `staleTime` is generous because live
 * invalidation will come from the backend's `/events` SSE stream, not from
 * frontend polling. Retries are limited to one: when the local server is
 * down, an employee should see that quickly rather than watch a spinner.
 */
export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        gcTime: 5 * 60_000,
        refetchOnWindowFocus: false,
        retry: 1,
      },
      mutations: {
        retry: 0,
      },
    },
  });
}

interface AppProvidersProps {
  readonly children: ReactNode;
  /** Tests inject an isolated client so no cache leaks between cases. */
  readonly queryClient?: QueryClient;
}

export function AppProviders({ children, queryClient }: AppProvidersProps) {
  // Stable across renders: a client rebuilt on every render would drop the
  // cache each time and defeat the point of the provider.
  const client = useMemo(() => queryClient ?? createQueryClient(), [queryClient]);
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
