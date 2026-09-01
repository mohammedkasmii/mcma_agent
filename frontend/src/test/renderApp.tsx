import type { ReactElement } from "react";
import { render } from "@testing-library/react";
import { createMemoryRouter, MemoryRouter, RouterProvider } from "react-router-dom";
import { appRoutes } from "@app/router";
import { AppProviders, createQueryClient } from "@app/providers";

/**
 * Mounts the application's real route table at a given address.
 *
 * Tests navigate by URL rather than by clicking through the shell, so a
 * routing regression fails here rather than in a screen test.
 */
export function renderAppAt(initialEntry: string) {
  const router = createMemoryRouter(appRoutes, { initialEntries: [initialEntry] });
  return render(
    <AppProviders queryClient={createQueryClient()}>
      <RouterProvider router={router} />
    </AppProviders>,
  );
}

/** Mounts a single component that needs router context but not the shell. */
export function renderWithRouter(ui: ReactElement, initialEntry = "/") {
  return render(<MemoryRouter initialEntries={[initialEntry]}>{ui}</MemoryRouter>);
}
