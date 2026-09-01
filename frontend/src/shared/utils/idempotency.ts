/**
 * Idempotency keys for job-creating requests.
 *
 * `crypto.randomUUID` is only exposed in a secure context. This application is
 * served locally and normally over TLS, but a plain-http LAN install would
 * leave it undefined — and a key generator that throws would block the agent
 * entirely. `crypto.getRandomValues` is available in both contexts, so it
 * backs the fallback. Math.random is never used: the key is what stops a
 * repeated request from creating a second automation.
 */
export function newIdempotencyKey(): string {
  if (typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
}
