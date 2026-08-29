# ADR-0003 — Read/write capability separation; write-incapable dry-run

**Status:** Accepted (design). **Baseline:** `0290fe9…`.

## Context
Today "preview"/"safety" mode is a boolean; row writes execute regardless (`docs/recovery/KNOWN_FAILURES.md` F1/F10),
and mission "verification" returns True without comparing (F3). A dry-run can write.

## Decision
The `portal` module constructs three narrow capabilities and nothing else hands out a write handle:
- **`ReadCapability`** — deny-by-default reads; search/open/scrape/read_rows; **no write method, never upgradable**. Dry-run uses only this.
- **`LoginCapability`** — auth/session contracts only; denies mission rows and all final endpoints (onboarding tool).
- **`VerifiedMissionWriter`** = `open_verified_writer(lease_handle, expected_identity)` — receives a `LeaseHandle` from
  `execution` (acquired via `persistence`; `portal` never reacquires the lock or imports sqlite, correction #5). Using
  **one BrowserContext**, it requires **exactly one** search match, opens it, and **fully re-verifies every identifier
  in that same context** (two-tier; **registration mandatory**; no match-by-absence) before attaching the write route
  and returning a writer exposing **explicit ops only** (`read_row/write_row/verify_row/trigger_native_recalc`). No
  generic request; charge-mutuelle not writable; row selection by exact `IdRubrique` (ADR-0004). Identity re-verified
  before the first write and after navigation (TOCTOU).

**Capability-neutral plans (correction #3):** a plan has no `mode`/`read_only`. Planning yields a `ProposedPlan`; only
execution authorization forms an `ApprovedPlanReference` and then an `ExecutablePlan` bound to a writer
(`DOMAIN_MODEL.md` §6). No boolean inside a plan can unlock writes. Dry-run has **no code path** to a writer →
write-incapable by construction. Row lifecycle: read-before-write → diff-before-write → fenced write → verify-after-write
→ atomic {transition+audit+outbox}.

## Consequences
- (+) INV-1, INV-2 enforced structurally; the write surface is explicit and minimal (pit of success).
- (−) More ceremony to obtain write access — intentional.
