// Audits the production build against the policy the server enforces.
//
// The CSP in mcma/app/security_headers.py allows no inline script, no inline
// style, no data: URI and no external origin. Vite is configured to satisfy
// that (assetsInlineLimit 0, cssCodeSplit false, modulePreload polyfill off),
// but configuration drifts and a plugin can reintroduce any of them silently.
// This turns "the page is blank in production because CSP blocked the entry
// script" into a failed build.
//
// Nothing here matches a hashed filename: the checks are on shape, not names.

import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, extname } from "node:path";
import { fileURLToPath } from "node:url";

const distDir = fileURLToPath(new URL("../dist", import.meta.url));

function walk(dir) {
  return readdirSync(dir).flatMap((entry) => {
    const full = join(dir, entry);
    return statSync(full).isDirectory() ? walk(full) : [full];
  });
}

const failures = [];

function fail(message) {
  failures.push(message);
}

let files;
try {
  files = walk(distDir);
} catch {
  console.error("no build output at dist/ — run `npm run build` first");
  process.exit(1);
}

const indexPath = join(distDir, "index.html");
const html = readFileSync(indexPath, "utf8");

// An inline script or style is exactly what script-src/style-src 'self' block.
if (/<script(?![^>]*\ssrc=)[^>]*>/i.test(html)) {
  fail("index.html contains an inline <script> block");
}
if (/<style[\s>]/i.test(html)) {
  fail("index.html contains an inline <style> block");
}
if (/\sstyle\s*=\s*"/i.test(html)) {
  fail("index.html contains an inline style attribute");
}

// Every referenced asset must be same-origin and root-relative.
for (const match of html.matchAll(/(?:src|href)\s*=\s*"([^"]+)"/gi)) {
  const url = match[1];
  if (/^https?:\/\//i.test(url) || url.startsWith("//")) {
    fail(`index.html references an external origin: ${url}`);
  }
  if (url.startsWith("data:")) {
    fail(`index.html references a data: URI: ${url}`);
  }
  if (!url.startsWith("/")) {
    fail(`index.html references a non-root-relative asset: ${url}`);
  }
}

// A data: asset in the bundles would be blocked by img-src 'self'. Bare
// occurrences of the word "data:" as an object key are not URIs, so the
// check looks for the URI shapes specifically.
const dataUri = /url\(\s*["']?data:|src\s*=\s*["']data:|["']data:[a-z]+\/[a-z0-9.+-]+/i;
for (const file of files) {
  const ext = extname(file);
  if (ext !== ".js" && ext !== ".css") continue;
  const contents = readFileSync(file, "utf8");
  if (dataUri.test(contents)) {
    fail(`${file} contains a data: asset URI`);
  }
  if (/sourceMappingURL/.test(contents)) {
    fail(`${file} references a sourcemap`);
  }
}

// Sourcemaps must not ship: they carry the readable source of an application
// that handles claim data.
for (const file of files) {
  if (file.endsWith(".map")) {
    fail(`build emitted a sourcemap: ${file}`);
  }
}

// Nothing but the index and hashed assets belongs in a served directory.
for (const file of files) {
  const relative = file.slice(distDir.length + 1).replaceAll("\\", "/");
  const allowed = relative === "index.html" || relative.startsWith("assets/");
  if (!allowed) {
    fail(`unexpected file in build output: ${relative}`);
  }
}

if (failures.length > 0) {
  console.error("build output audit failed:");
  for (const failure of failures) console.error(`  - ${failure}`);
  process.exit(1);
}

console.log(`build output audit passed (${files.length} files)`);
