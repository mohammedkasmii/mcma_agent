import { fileURLToPath } from "node:url";
import { defineConfig } from "@playwright/test";

/**
 * Browser E2E against the REAL FastAPI application serving the REAL build.
 *
 * The server is composed by e2e/e2e_support/server.py from the same
 * create_api_app() + mount_frontend() the production entry point uses, so
 * what these tests exercise is the actual serving contract — route
 * precedence, the SPA fallback, the CSP header, /assets and /events — not a
 * stand-in. It binds loopback HTTP because principal resolution for the
 * single-office install requires a loopback client; production remains
 * HTTPS-only and that is not under test here.
 *
 * Paths are resolved absolutely from this file rather than written as
 * strings relative to some assumed working directory. `cwd` moves to the
 * repository root so `mcma` imports the way it does everywhere else, which
 * means a PYTHONPATH entry written as "./e2e" would resolve against the
 * root and silently miss frontend/e2e. An absolute entry cannot.
 *
 * The interpreter is `python`, not `python3`: Windows installs and the
 * actions/setup-python shim both provide `python`, and `python3` does not
 * exist on a standard Windows install.
 */
const PORT = 8788;

const repoRoot = fileURLToPath(new URL("..", import.meta.url));
const e2eDir = fileURLToPath(new URL("./e2e", import.meta.url));

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  timeout: 30_000,
  expect: { timeout: 10_000 },
  reporter: process.env["CI"] ? "list" : "line",
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    trace: "off",
    video: "off",
  },
  webServer: {
    command: `python -m e2e_support.server ${PORT}`,
    cwd: repoRoot,
    // One absolute entry, so no platform-specific path separator is needed.
    env: { PYTHONPATH: e2eDir },
    url: `http://127.0.0.1:${PORT}/health`,
    reuseExistingServer: false,
    timeout: 60_000,
  },
});
