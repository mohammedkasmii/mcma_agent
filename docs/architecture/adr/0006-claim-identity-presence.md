# ADR-0006 — Claim identity (account_id + idSinistre) & category-presence history

**Status:** Accepted (design). **Baseline:** `0290fe9…`.

## Context
The current cache overwrites a full snapshot each poll — no stable identity, no history, no presence lifecycle. The
resolved rule (`docs/recovery/BUSINESS_RULES.md` B.9) requires idSinistre identity and a complete-poll absence rule.

## Decision
Stable claim identity = **`UNIQUE(account_id, portal_claim_id)`** where `portal_claim_id` (idSinistre) is **NOT NULL and
required before insertion** into `claims`. Notifications lacking an idSinistre go to a **staging** table
`unmatched_notifications`, never into `claims`, and never weaken uniqueness. **Category membership is modelled
separately** (`category_presence`), so a claim moving between categories is not a duplicate. **Presence lifecycle:**
`ACTIVE → MISSING_PENDING_CONFIRMATION → RESOLVED_ON_PORTAL` only after **3 consecutive complete, valid-session** polls
absent; a PARTIAL/FAILED/invalid poll neither increments nor resets `consecutive_absence_count`; observing the claim
again resets to ACTIVE. Fields: `presence_status`, `consecutive_absence_count`, `last_complete_poll_version`.

## Consequences
- (+) Correct de-duplication and a truthful presence lifecycle; no phantom "resolved" from a flaky poll.
- (−) Requires the staging model and poll-completeness tracking (`poll_runs`).
