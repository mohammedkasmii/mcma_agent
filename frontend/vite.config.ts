/// <reference types="vitest/config" />
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const fromRoot = (segment: string) => fileURLToPath(new URL(segment, import.meta.url));

/**
 * The served application must satisfy the backend Content-Security-Policy
 * (mcma/app/dashboard.py): script-src 'self'; style-src 'self'; img-src 'self'.
 *
 * Two build settings exist purely to keep that true:
 *   - assetsInlineLimit: 0  -> no asset is ever emitted as a data: URI,
 *     which img-src 'self' would refuse.
 *   - cssCodeSplit: false   -> one external stylesheet, never an inline
 *     <style> element injected at runtime.
 * modulePreload.polyfill is off because the polyfill is injected as an
 * inline module script, which script-src 'self' would refuse.
 */
export default defineConfig({
  plugins: [react()],
  /**
   * Root-absolute, not "./". The application is served at / and uses
   * BrowserRouter, so the same index document is returned for a deep address
   * such as /accounts/<id>/work. A relative base would make that document
   * resolve its JS and CSS against /accounts/<id>/, which 404s.
   */
  base: "/",
  resolve: {
    alias: {
      "@app": fromRoot("./src/app"),
      "@features": fromRoot("./src/features"),
      "@shared": fromRoot("./src/shared"),
    },
  },
  build: {
    outDir: "dist",
    assetsInlineLimit: 0,
    cssCodeSplit: false,
    modulePreload: { polyfill: false },
    sourcemap: false,
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
    include: ["src/**/*.test.{ts,tsx}"],
    // e2e/ is Playwright's; Vitest must not try to run those specs.
    exclude: ["e2e/**", "node_modules/**", "dist/**"],
  },
});
