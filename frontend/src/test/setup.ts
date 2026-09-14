import "@testing-library/jest-dom/vitest";
import { cleanup, configure } from "@testing-library/react";
import { afterEach, vi } from "vitest";

// Every screen case mounts the whole shell -- rail, header, route -- and
// waits on at least two fetch round trips, while vitest runs test files in
// parallel. Testing Library's 1s default sits just under that on a loaded
// machine, which showed up as findBy failures that passed in isolation.
// This raises the ceiling only: a query that never resolves still fails the
// test, it just takes longer to say so.
configure({ asyncUtilTimeout: 5000 });

// Each test mounts into a fresh document with a fresh network double;
// leftovers from a previous case would make queries ambiguous and let one
// test's stubbed fetch answer another test's request.
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});
