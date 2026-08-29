# ARCHITECTURE

**Baseline (production code):** `0290fe9df24c9e2f2b054ee4f8b14b8267f07b12`
**Recovery-docs revision:** `b0ac1c1c6ba15d4efef8385195455f72b8e90e19`
**Status:** Phase 3 — target architecture (design only). Production code is unchanged at baseline; every gap here is
Phase 4 migration backlog, not a defect of this document. See `TRACEABILITY_MATRIX.md` for per-item compliance.

This document is the entry point. Detail lives in the sibling documents and the ADRs (`adr/`).

---

## 1. Objective

Preserve the stable working features of the MCMA SinAuto agent (mapping, notification extraction, employee dashboard)
while fixing the confirmed safety, correctness, security and maintainability defects in `docs/recovery/KNOWN_FAILURES.md`
and enforcing the invariants in `docs/recovery/SAFETY_INVARIANTS.md`. **Incremental, not a rewrite.**

## 2. Selected architecture — Incremental Modular Monolith

One deployable FastAPI service (one Uvicorn worker) on the single on-prem office server, internally split into
modules with a one-directional dependency rule. SQLite (WAL) for durable state. In-process async job runner with a
**DB-backed per-account lease** as the authoritative single-writer guarantee. A single `portal` gateway owns
Playwright and all capability/interception logic. SSE (one authorized stream per account) fed by a transactional outbox.

### Alternatives considered (evidence in ADR-0001)
- **A. Modular monolith (SELECTED)** — fewest moving parts; matches one-server/few-accounts/low-concurrency reality;
  centralizes capability control in one gateway (decisive safety win); reachable feature-by-feature from baseline; easy rollback.
- **B. Decomposed services + broker (rejected)** — fault isolation and horizontal scale, but heavy for a single office;
  distributed default-deny and cross-process single-writer add risk and ops cost with no load to justify them.
- **C. Patch-in-place (rejected)** — smallest change but leaves the maintainability and capability-separation defects intact.

**Recommendation:** A, with module seams that would permit later extraction of `portal`/`execution` into a worker
process (toward B) **if** load ever demands it — no redesign required.

## 3. Module map (ownership)

`core` · `domain` · `mapping` · `planning` · `persistence` · `portal` · `execution` · `notifications` · `app` · `web`.
Dependency rules, ownership constraints and the `AuthProvider` seam are in `MODULE_BOUNDARIES.md`. Arrow convention in
every diagram: **`X → Y` means "X depends on / imports Y"**.

## 4. Cross-cutting decisions (index)
| Concern | Where |
|---|---|
| Typed inputs, normalization (glass/labour/origin), deterministic plans | `DOMAIN_MODEL.md`, ADR-0002 |
| Workflow registry, DRY_RUN vs EXECUTE state machines, human handoff | `WORKFLOW_STATE_MODEL.md`, ADR-0002 |
| Capability separation, context-level default-deny, final-endpoint block, identity gate, lease fencing, session vault/DPAPI | `SAFETY_MODEL.md`, ADR-0003/0004/0007 |
| SQLite WAL schema, at-rest protection, outbox, SSE retention, backup, migrations | `DATA_MODEL.md`, ADR-0005/0006/0009 |
| TLS, auth (Argon2id, sessions, CSRF, AuthProvider), RBAC, endpoints, SSE | `API_CONTRACTS.md`, ADR-0008/0009 |
| Test architecture (unconditional prod-domain block, property-based, safety) | `TEST_STRATEGY.md` |
| Threats, trust boundaries, mitigations | `THREAT_MODEL.md` |
| Requirement → module → ADR → test → compliance | `TRACEABILITY_MATRIX.md` |

## 5. Deployment (target)

- **Single Windows service, one Uvicorn worker** (`--workers 1`). Correctness of the per-account single-writer relies
  on the DB `account_leases` (authoritative, cross-process); the in-process `asyncio.Lock` is only a fast path.
  Running >1 worker is unsupported and refused at startup.
- **TLS is required** for authenticated LAN deployment (ADR-0008, `API_CONTRACTS.md` §TLS): an internal CA issues the
  server certificate; the CA root is distributed to office machines; certificates are renewed on a schedule with
  overlap; on certificate failure the service **does not start / does not serve** — **authentication never silently
  falls back to plain HTTP**.
- **At-rest protection required now** (ADR-0005, `DATA_MODEL.md`): BitLocker on the server volume + strict NTFS ACLs on
  the DB directory + encrypted, access-controlled backups + DB never under a served directory + no PII in
  logs/outbox/screenshots/plan snapshots. If BitLocker + encrypted backups cannot be guaranteed, SQLCipher (or
  equivalent DB encryption) becomes mandatory before storing production PII.
- **Interactive onboarding/login** runs as a separate desktop-session tool (headed Chromium for OTP); server jobs are headless.
- **Backups:** SQLite online backup API / WAL-coordinated procedure; **never** a plain copy of a running DB.

## 6. Incremental migration order (safety-first; detail is Phase 4, not here)
1. Unconditional production-domain test blocking. 2. Characterization tests pinning current mapper/notifier behaviour.
3. Typed inputs + deterministic plans. 4. Read/write capability separation + context-level fail-closed interception.
5. Mission identity gate. 6. Permanent final-endpoint block (abort, not fake-200). 7. Persistence (SQLite WAL) + outbox
+ SSE. 8. Auth/RBAC + TLS. 9. Migrate workflows behind feature flags. 10. Dashboard/UX. **No big-bang; each step is
independently revertible via feature flags and reversible-where-safe migrations + tested backup/restore.**

## 7. What is preserved
Wexia mapping semantics (with the corrected three-origin/glass/labour/negative-TVA rules), notification extraction
(`length=-1` strategy), the employee dashboard, and the human-final-validation principle. No working feature is dropped;
`FINALIZED_BY_HUMAN` remains a human action the agent never performs.
