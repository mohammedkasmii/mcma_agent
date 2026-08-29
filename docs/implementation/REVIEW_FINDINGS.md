# Phase 4 Review Findings

Reviews run after drafting the plan: (a) contradiction review, (b) spec-to-code-compliance vs baseline `0290fe9`,
(c) sharp-edges footgun review, (d) insecure-defaults/security review, (e) test-strategy review, (f) DB-migration &
crash-recovery review, and (g) independent second-opinion. Four bounded **read-only** review subagents supplied
independent findings; the primary agent verified and synthesized them (no subagent modified files or decided anything).

**Disposition key:** ACCEPTED (doc changed) · DEFERRED (recorded, not blocking; owner may action later) · REJECTED (with reason).

## A. Reviews that produced no change
- **Contradiction review (recovery ↔ architecture ↔ implementation):** clean. No plan statement contradicts a recovery
  decision or an ADR. One *omission* surfaced (WORKFLOW_STATE_MODEL §7 does not enumerate the `IDENTITY_VERIFIED` /
  `READ_ONLY_IDENTITY_CHECK` restart outcomes) — resolved in the plan (INC-12) and flagged as a deferred architecture
  touch-up (see SR-3 below and §Remaining decisions).
- **Spec-to-code-compliance vs `0290fe9`:** the plan is consistent with the Phase 3 baseline classification. Every
  `CURRENTLY_NONCOMPLIANT` / `PARTIALLY_COMPLIANT` / `NOT_IMPLEMENTED` item maps to a primary increment (the Phase 4
  backlog); the three `CURRENTLY_COMPLIANT` items (Decimal money, human-final-validation, relance-not-mutated) are
  preserved and re-asserted (INC-04/12/14). The plan makes **no** claim that the baseline already satisfies a target.
- **Insecure-defaults:** no fail-open default remains after the accepted changes (at-rest gate, TLS refuse-without-cert,
  no default credentials, subnet-never-disables-auth, route-handler-abort, write-enable not a boolean). Findings folded
  into the sharp-edges/security items below.

## B. Second-opinion (external) — UNAVAILABLE, not fabricated
The external reviewer could not run: `codex` and `gemini` CLIs are **not installed** on this machine and the Codex
review MCP server failed to connect this session. No external review was fabricated. In its place, four **independent
read-only review subagents** (traceability, safety/security, DB/crash-recovery, API-auth/test-strategy) plus the
sharp-edges and insecure-defaults passes provided the independent critique. If a CLI is installed later
(`npm i -g @openai/codex`), the external review can be run against the created docs on request.

## C. Sharp-edges / insecure-defaults (primary agent)
| ID | Finding | Sev | Disposition | Doc changed |
|---|---|---|---|---|
| SE-1 | `job_inputs` could be stored with a weak/stub encryptor if DPAPI absent | High | ACCEPTED | INC-12 (fail-closed encryptor; refuse to store) |
| SE-2 | Legacy unauth API must be loopback-only during migration | High | ACCEPTED (superseded/strengthened by SEC-6 → INC-00) | INC-16, INC-00 |
| SE-3 | Test-only crypto/mutex backends must not be importable in production | Med | ACCEPTED (reinforced by SEC-4) | INC-13, INC-11 |

## D. Safety/Security review subagent
| ID | Finding | Sev | Disposition | Doc changed |
|---|---|---|---|---|
| SEC-1 | **Baseline's own live-write paths run for the whole rebuild**; egress lockdown is test-only | High/Crit | ACCEPTED | **New INC-00** baseline containment; README; RELEASE_GATES |
| SEC-2 | INC-01 proof tests dial the real portal + rely on a runbook (emits traffic if OS denial absent) | Med-High | ACCEPTED | INC-01 (no-emission preflight; sentinel target; fail-closed) |
| SEC-3 | "mock allowed / live OFF" could be a `TEST_MODE`-style flag | Med | ACCEPTED | INC-09 (structural loopback-host contract + test); INC-06 |
| SEC-4 | Test backends lack a production fail-closed guard | Med | ACCEPTED | INC-11/INC-13 (`test_production_rejects_*` + non-importable) |
| SEC-5 | DPAPI LocalMachine confidentiality rests on an ACL asserted only "where feasible" | Med | ACCEPTED | INC-13 (hard ACL precondition; refuse store if unset) |
| SEC-6 | Legacy unauth API contained only by documentation | Med | ACCEPTED | INC-00 (structural loopback bind + remove `profile=any` firewall now) |
| SEC-7 | INC-23 "(b) safety suite green" not runtime-verifiable → risk of a stored boolean | Low-Med | ACCEPTED | INC-23 (data-driven `confirmed_row_ops`; suite-green is a CI precondition tied to the same commit) |

## E. DB-migration & crash-recovery review subagent
| ID | Finding | Sev | Disposition | Doc changed |
|---|---|---|---|---|
| SR-1 | `portal_sessions` missing from INC-10 schema list though INC-13 depends on it | High | ACCEPTED | INC-10 (all 20 tables incl. `portal_sessions`) |
| SR-2 | `ACQUIRING_ACCOUNT_LOCK`/`IDENTITY_VERIFYING` → `ABORTED_ON_RESTART` untested | Med | ACCEPTED | INC-12 (test added) |
| SR-3 | `IDENTITY_VERIFIED` restart outcome undefined in §7 **and** plan | Med | ACCEPTED (plan) / DEFERRED (architecture §7 enumeration) | INC-12 (pre-write → `ABORTED_ON_RESTART`+release lease, tested); architecture §7 enumeration flagged for owner approval |
| SR-4 | `READ_ONLY_IDENTITY_CHECK` restart outcome undefined | Low | ACCEPTED | INC-12 (→ back to `QUEUED`, tested) |
| SR-5 | Stale-lease release on restart not planned/tested | Low-Med | ACCEPTED | INC-12 (test added) |
| SR-6 | No idempotency guard against double-counting the same poll run per category | Low | ACCEPTED | INC-14 (test added; `last_complete_poll_version`) |
| SR-7 | Expand/contract migration discipline not stated/tested | Low | ACCEPTED | INC-10 (policy + test) |

## F. API/Auth & test-strategy review subagent
| ID | Finding | Sev | Disposition | Doc changed |
|---|---|---|---|---|
| AR-H1 | List endpoints not proven to row-filter to accessible accounts (leak risk) | High | ACCEPTED | INC-17 (`test_list_endpoints_return_only_authorized_accounts`) |
| AR-M1 | Session idle/absolute expiry + logout invalidation untested | Med | ACCEPTED | INC-16 (two tests) |
| AR-M2 | Per-account enforcement asserted generically, not per surface | Med | ACCEPTED | INC-17 (parametrized per-surface test) |
| AR-M3 | Client-supplied `authorized_by` rejection untested at executions | Med | ACCEPTED | INC-17 (test added) |
| AR-M4 | Rollback proof is a runbook, not an executed test | Med | ACCEPTED | INC-22 + TEST_PLAN (`test_rollback_flag_flip_returns_to_last_green`) |
| AR-L1 | `Secure` cookie attribute not explicitly tested | Low | ACCEPTED | INC-16 |
| AR-L2 | AuthProvider seam substitution untested | Low | ACCEPTED | INC-16 |
| AR-L3 | Correlation-id / redaction untested | Low | ACCEPTED | INC-17 |
| AR-L4 | INC-18 forbids any HTTP listener vs API_CONTRACTS §1 optional redirect | Low | ACCEPTED | INC-18 (intentionally HTTPS-only; redirect is an external proxy) |
| AR-L5 | `idempotency_key` on dry-runs untested | Low | ACCEPTED | INC-17 |
| AR-L6 | Cert renewal-with-overlap is runbook-only | Low | DEFERRED | operational; acceptable as a runbook (INC-18) |

## G. Traceability/completeness review subagent
| ID | Finding | Sev | Disposition | Doc changed |
|---|---|---|---|---|
| TR-INV5 | INV-5 primary (INC-12) did not own it / lacked a terminal-state test | Med | ACCEPTED | INC-12 (addresses INV-5 + `test_readiness_terminal_at_ready_for_human_review`) |
| TR-F31 | Keep-alive daemon scheduling/escalation not owned by any increment | Med | ACCEPTED | INC-14 (session-refresh poller under lease; F31 added); backlog |
| TR-KEEPALIVE | "Session keep-alive daemon" preserved feature had no row/owner | Med | ACCEPTED | INC-14; backlog §5 row added |
| TR-CRITPATH | Stated linear critical path misrepresented parallel branches | Med | ACCEPTED | REBUILD_ROADMAP (corrected; three branches converge at INC-23) |
| TR-B4 | INC-04 header omitted B.4 (rule was implemented/tested) | Low | ACCEPTED | INC-04 |
| TR-B8 | B.8 omitted INC-10 (accounts registry schema) | Low | ACCEPTED | backlog |
| TR-F12 | F12 citation understates its spread across INC-05/09/19/22 | Low | DEFERRED | aggregate coverage adequate; noted here |
| TR-OBSFIN | `observed_finalizations ≠ job status` had no behavioral owner | Low | ACCEPTED | INC-12 (readiness terminal test asserts it) |

**Confirmation:** no review found a **dropped** requirement (no missing INV, F, ADR, or business rule). The only genuinely
unmapped preserved artifact (the session keep-alive daemon) now has a primary owner (INC-14). All ACCEPTED findings were
corrected in the documents named above.

## Remaining decisions for the owner (see also OPEN items)
1. **Architecture §7 enumeration (SR-3, deferred):** `WORKFLOW_STATE_MODEL.md` §7 should be amended to explicitly list
   `IDENTITY_VERIFIED` and `READ_ONLY_IDENTITY_CHECK` restart outcomes to match the plan (both are pre-write / read-only →
   fail-closed). The plan already specifies the safe deterministic behavior; this is a one-paragraph architecture-doc
   consistency fix held for owner approval since Phase 4 scope is `docs/implementation/` only.
2. **Cert renewal automation (AR-L6, deferred):** whether to automate renewal-with-overlap or keep it a runbook step.
