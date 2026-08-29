# ADR-0006 — Claim identity (account_id + idSinistre) & category-presence history

**Status:** Accepted (design). **Baseline:** `0290fe9…`.

## Context
The current cache overwrites a full snapshot each poll — no stable identity, no history, no presence lifecycle. The
resolved rule (`docs/recovery/BUSINESS_RULES.md` B.9) requires idSinistre identity and a complete-poll absence rule.

## Decision
Stable claim identity = **`UNIQUE(account_id, portal_claim_id)`** where `portal_claim_id` (idSinistre) is **NOT NULL and
required before insertion** into `claims`. Notifications lacking an idSinistre go to a **staging** table
`unmatched_notifications`, never into `claims`, and never weaken uniqueness.

**Presence is category-scoped (correction #1):** the claim carries **no** presence lifecycle. The lifecycle lives on
`category_presence`, independently per **`(account_id, claim_pk, category_code)`** — fields `presence_status`,
`consecutive_absence_count`, `last_complete_poll_version` were **moved there** from `claims`. Per-category completeness
is recorded in **`poll_run_categories(poll_run_id, category_code, status, session_valid, completed_at, rows_seen)`**.

**Per-category lifecycle:** `ACTIVE → MISSING_PENDING_CONFIRMATION → RESOLVED_ON_PORTAL` for a given category only after
**3 consecutive** polls in which **that exact category** completed successfully under a valid session and the claim was
absent. A category that fetched PARTIAL/FAILED/invalid neither increments nor resets its own counter **and never affects
another category**. Observing the claim in a completed poll of that category resets it to ACTIVE.

## Consequences
- (+) Correct de-duplication and a truthful presence lifecycle; no phantom "resolved" from a flaky poll.
- (−) Requires the staging model and poll-completeness tracking (`poll_runs`).
