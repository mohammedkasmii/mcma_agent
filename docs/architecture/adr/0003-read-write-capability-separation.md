# ADR-0003 — Read/write capability separation; write-incapable dry-run

**Status:** Accepted (design). **Baseline:** `0290fe9…`.

## Context
Today "preview"/"safety" mode is a boolean; row writes execute regardless (`docs/recovery/KNOWN_FAILURES.md` F1/F10),
and mission "verification" returns True without comparing (F3). A dry-run can write.

## Decision
The `portal` module constructs three narrow capabilities and nothing else hands out a write handle:
- **`ReadCapability`** — deny-by-default reads; search/open/scrape/read_rows; **no write method, never upgradable**. Dry-run uses only this.
- **`LoginCapability`** — auth/session contracts only; denies mission rows and all final endpoints (onboarding tool).
- **`VerifiedMissionWriter`** = `open_verified_writer(account_id, expected_identity)` — internally acquires lease+lock,
  requires **exactly one** search match, opens it, compares **every** identifier (two-tier; no match-by-absence), and
  only then returns a writer exposing **explicit ops only** (`read_row/write_row/verify_row/trigger_native_recalc`). No
  generic request; charge-mutuelle not writable. Identity re-verified before the first write and after navigation (TOCTOU).

Dry-run has **no code path** to a writer → write-incapable by construction (not a boolean). Row lifecycle:
read-before-write → diff-before-write → fenced write → verify-after-write → atomic {transition+audit+outbox}.

## Consequences
- (+) INV-1, INV-2 enforced structurally; the write surface is explicit and minimal (pit of success).
- (−) More ceremony to obtain write access — intentional.
