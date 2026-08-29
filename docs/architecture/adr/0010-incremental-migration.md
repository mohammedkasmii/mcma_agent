# ADR-0010 — Incremental migration strategy

**Status:** Accepted (design). **Baseline:** `0290fe9…`.

## Context
The project must reach the target architecture **without a big-bang rewrite**, preserving working features and keeping
every step revertible. Production code is unchanged at baseline; this ADR governs how Phase 4/5 proceed.

## Decision
Migrate **safety-first**, one increment at a time, each behind a feature flag and covered by tests before cutover:
1. **Unconditional production-domain test blocking** (socket guard). 2. **Characterization tests** pinning current
mapper/notification behaviour. 3. **Typed inputs + deterministic plans** (fail-closed mapping). 4. **Read/write capability
separation + context-level fail-closed interception**. 5. **Mission identity gate**. 6. **Permanent final-endpoint block**
(abort, not fake-200). 7. **SQLite WAL persistence + outbox + SSE**. 8. **Auth/RBAC + TLS**. 9. **Migrate workflows behind
flags** (keep JSON cache until DB parity is proven, then switch reads). 10. **Dashboard/UX**.

**Guardrails:** each step is independently revertible via feature flags; migrations are compatibility-aware
(expand/contract) with a tested backup/restore runbook (not all are reversible); the `TRACEABILITY_MATRIX.md`
classification (CC/CN/PC/NI/NA) is the migration backlog and is updated as items land.

## Consequences
- (+) Continuous working system; safety lands before any live write is enabled; low rollback risk.
- (−) Slower than a rewrite, and requires flag/branch discipline — accepted deliberately.
