# ADR-0009 — SSE + delta recovery via outbox + monotonic versions

**Status:** Accepted (design). **Baseline:** `0290fe9…`.

## Context
No live updates today (button-click refresh only). A naive per-account version as the SSE cursor is not globally unique
across a multi-account stream, and a single `delivered` boolean cannot represent N clients.

## Decision
- **SSE cursor = the global `event_outbox.event_id`** (monotonic across all accounts), used as the SSE `id:` and
  `Last-Event-ID`. Per-account `account_state_version` lives **inside the payload**.
- **Default: one authorized stream per account** (`/events/stream?account_id=…`); a multiplexed, server-filtered stream
  is an option. Replay on reconnect returns `event_id > cursor`, **authorization-filtered**.
- **Retention** is **bounded by time and count** (configurable), **independent of any client cursor** — a disconnected
  or idle client never blocks cleanup. If a reconnecting cursor is **older than the earliest retained event**, the server
  sends a **full-state snapshot (forced resync)**, then resumes deltas.
- **Long-lived authorization** is revalidated periodically; on revocation the stream is dropped/rebuilt. No single
  `delivered` boolean is treated as a delivery guarantee (`published_at` marks fan-out progress only).

## Consequences
- (+) Correct ordering and recovery across reconnects; no missed or over-shared events; cleanup is not held hostage by idle clients.
- (−) Requires snapshot generation and retention/cleanup jobs.
