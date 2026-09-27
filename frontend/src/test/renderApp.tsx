import type { ReactElement } from "react";
import { render } from "@testing-library/react";
import { QueryClient } from "@tanstack/react-query";
import { createMemoryRouter, MemoryRouter, RouterProvider } from "react-router-dom";
import { appRoutes } from "@app/router";
import { AppProviders } from "@app/providers";
import { AuthProvider } from "@features/auth/AuthProvider";
import type { AuthSession } from "@shared/types";

/** The default signed-in user: existing screen tests are about screens, not sign-in. */
export const TEST_SESSION: AuthSession = {
  userId: "user-1",
  username: "admin",
  role: "admin",
  permissions: [],
  accountIds: [],
  localSingleUser: false,
};

export interface RenderAppOptions {
  /**
   * A session to start with (default: TEST_SESSION, no /auth/me request), or
   * "probe" to run the real /auth/me check against the fetch double.
   */
  readonly auth?: AuthSession | "probe";
  /** Shortens the session-recheck cooldown so tests need not wait 5s. */
  readonly recheckCooldownMs?: number;
}

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
export function renderAppAt(
  initialEntry: string,
  queryClient?: QueryClient,
  options: RenderAppOptions = {},
) {
  const router = createMemoryRouter(appRoutes, { initialEntries: [initialEntry] });
  const auth = options.auth ?? TEST_SESSION;
  const cooldown =
    options.recheckCooldownMs === undefined ? {} : { recheckCooldownMs: options.recheckCooldownMs };
  return {
    router,
    ...render(
      <AppProviders queryClient={queryClient ?? createTestQueryClient()}>
        {auth === "probe" ? (
          <AuthProvider {...cooldown}>
            <RouterProvider router={router} />
          </AuthProvider>
        ) : (
          <AuthProvider initialSession={auth} {...cooldown}>
            <RouterProvider router={router} />
          </AuthProvider>
        )}
      </AppProviders>,
    ),
  };
}

/**
 * Mounts a single component that needs router context but not the shell.
 *
 * The query provider is included because rail items now carry their own
 * connection mutation; a component under test should not have to be composed
 * differently from how the application composes it.
 */
export function renderWithRouter(ui: ReactElement, initialEntry = "/") {
  return render(
    <AppProviders queryClient={createTestQueryClient()}>
      <MemoryRouter initialEntries={[initialEntry]}>{ui}</MemoryRouter>
    </AppProviders>,
  );
}
