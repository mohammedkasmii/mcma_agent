import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

// Each test mounts into a fresh document with a fresh network double;
// leftovers from a previous case would make queries ambiguous and let one
// test's stubbed fetch answer another test's request.
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});
