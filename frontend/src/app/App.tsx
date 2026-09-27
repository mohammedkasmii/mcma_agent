import { RouterProvider } from "react-router-dom";
import { AuthProvider } from "@features/auth/AuthProvider";
import { AppProviders } from "./providers";
import { createAppRouter } from "./router";

const router = createAppRouter();

/**
 * The application root. It composes two things and holds no logic of its
 * own: screens live in features/, the frame lives in AppShell, and the
 * route table lives in router.tsx.
 */
export function App() {
  return (
    <AppProviders>
      <AuthProvider>
        <RouterProvider router={router} />
      </AuthProvider>
    </AppProviders>
  );
}
