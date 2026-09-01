import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// Each test mounts into a fresh document; leftover trees from a previous
// case would make text queries ambiguous.
afterEach(() => {
  cleanup();
});
