import type { ReactElement } from "react";
import { render } from "@testing-library/react";
import { QueryClient } from "@tanstack/react-query";
import { createMemoryRouter, MemoryRouter, RouterProvider } from "react-router-dom";
import { appRoutes } from "@app/router";
import { AppProviders } from "@app/providers";

/**
 * A query client for tests: no retries, no cache reuse between cases.
 * Retrying would make an error-state assertion wait on backoff, and a shared
 * cache would let one test's accounts appear in another's rail.
 */
export function createTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0, staleTime: 0 },
      mutations: { retry: false },
    },
  });
}

/**
 * Mounts the application's real route table at a given address.
 *
 * Tests navigate by URL rather than by clicking through the shell, so a
 * routing or guard regression fails here rather than in a screen test.
 */
export function renderAppAt(initialEntry: string, queryClient?: QueryClient) {
  const router = createMemoryRouter(appRoutes, { initialEntries: [initialEntry] });
  return render(
    <AppProviders queryClient={queryClient ?? createTestQueryClient()}>
      <RouterProvider router={router} />
    </AppProviders>,
  );
}

/** Mounts a single component that needs router context but not the shell. */
export function renderWithRouter(ui: ReactElement, initialEntry = "/") {
  return render(<MemoryRouter initialEntries={[initialEntry]}>{ui}</MemoryRouter>);
}
