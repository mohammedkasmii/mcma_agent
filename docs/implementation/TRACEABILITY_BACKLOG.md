# Traceability & Backlog Completeness

Every safety invariant, known failure, ADR, business rule, preserved feature, and architecture-noncompliance item maps
to **exactly one primary increment** (plus supporting increments). Nothing from Phase 3 disappears silently.

Columns for every table below: **Primary** (exactly one) · **Supporting** · **Planned test/evidence** · **Gate** (or N/A)
· **Target module** · **Status** (Planned, or Preserved/re-asserted for baseline-CC items).

## 1. Safety invariants (INV-1..INV-11)
| INV | Primary | Supporting | Test/evidence | Gate | Target module | Status |
|---|---|---|---|---|---|---|
| INV-1 dry-run write-incapable | INC-08 | INC-09 | dry-run-has-no-writer | G2 | `mcma/portal` | Planned |
| INV-2 mission identity | INC-09 | — | identity mismatch/zero/multiple | G2 | `mcma/portal` | Planned |
| INV-3 default-deny interception | INC-07 | — | unknown-request-aborts | G2 | `mcma/portal` | Planned |
| INV-4 final endpoints blocked | INC-07 | INC-23 | final-abort-not-fake200 | G2/G5 | `mcma/portal` | Planned |
| INV-5 human final validation | INC-12 | INC-23 | readiness-terminal (`observed_finalizations`≠job) | G3/G5 | `mcma/execution` | Preserved/re-asserted |
| INV-6 fail-closed mapping (+exact rubrique) | INC-04 | INC-05, INC-09 | fail-closed props; exact-IdRubrique | G1/G2 | `mcma/domain`,`mcma/portal` | Planned |
| INV-7 Decimal, no negative TVA | INC-04 | — | negative-TVA-fails-closed | G1 | `mcma/domain` | Planned |
| INV-8 charge-mutuelle native-only | INC-09 | INC-12, INC-23 | never-directly-written **+** native-triggered **+** exact-summary-verified before readiness | G2/G5 | `mcma/portal`,`mcma/execution` | Planned |
| INV-9 relance not mutated | INC-14 | — | extraction-read-only | N/A | `mcma/notifications` | Preserved/re-asserted |
| INV-10 secrets/PII | INC-13 | INC-19, INC-20, INC-21 | vault/logs/xss/at-rest | G3/G-PDR | `mcma/portal`,`mcma/persistence` | Planned |
| INV-11 API authn / no LAN exposure | INC-16 | INC-17, INC-18 | auth/authz/TLS | G4 | `mcma/app` | Planned |

## 2. Known failures (F1..F33 — each listed individually)
| F | Primary | Supporting | Test/evidence | Gate | Target module | Status |
|---|---|---|---|---|---|---|
| F1 preview clicks row checkmarks | INC-07 | INC-08, INC-09, INC-23 | preview-no-write | G2 | `mcma/portal` | Planned |
| F2 preview POSTs updateDevisDet | INC-07 | INC-09, INC-23 | unknown/allowlist-gated | G2 | `mcma/portal` | Planned |
| F3 first-row mission fallback | INC-09 | — | first-row-rejected | G2 | `mcma/portal` | Planned |
| F4 sole-candidate fallback | INC-09 | — | zero/multiple fail-closed | G2 | `mcma/portal` | Planned |
| F5 partial matches → writes | INC-09 | — | partial-match fail-closed | G2 | `mcma/portal` | Planned |
| F6 forced charge-mutuelle | INC-09 | INC-00, INC-22 | never-directly-written + native-triggered + exact-summary-verified; baseline path removed | G2 | `mcma/portal` | Planned |
| F7 duplicate checkmark | INC-09 | — | single-write-no-duplicate | G2 | `mcma/portal` | Planned |
| F8 fail-open interceptor | INC-07 | — | abort-not-fake200 | G2 | `mcma/portal` | Planned |
| F9 page-scoped interception | INC-07 | — | context-scoped | G2 | `mcma/portal` | Planned |
| F10 dry-run retains write access | INC-08 | INC-09 | dry-run-no-writer | G2 | `mcma/portal` | Planned |
| F11 mapping_status unused | INC-05 | — | NeedsReview-blocks-writeable | G1 | `mcma/planning` | Planned |
| F12 false Verified/READY/Prêt | INC-19 | INC-05, INC-09, INC-12, INC-22 | truthful-readiness | G4 | `mcma/web`,`mcma/app` | Planned |
| F13 glass→rubrique 1 | INC-04 | — | glass-19-24-fail-closed | G1 | `mcma/domain` | Planned |
| F14 out-of-catalogue default | INC-04 | — | out-of-catalogue-fail-closed | G1 | `mcma/domain` | Planned |
| F15 `"mo"` token over-match | INC-04 | — | no-mo-substring | G1 | `mcma/domain` | Planned |
| F16 rubrique-row selection | INC-09 | — | exact-IdRubrique zero/multiple | G2 | `mcma/portal` | Planned |
| F17 negative TVA | INC-04 | — | negative-TVA-fail-closed | G1 | `mcma/domain` | Planned |
| F18 unauth LAN API | INC-16 | INC-00, INC-17, INC-18 | auth-required; baseline contained | G4 | `mcma/app` | Planned |
| F19 error leakage (str(e)) | INC-17 | — | typed-non-sensitive-errors | G4 | `mcma/app` | Planned |
| F20 HTTP-200-on-failure | INC-17 | — | truthful-status | G4 | `mcma/app` | Planned |
| F21 PII in logs | INC-20 | INC-13 | log-redaction | G-PDR | `mcma/core` | Planned |
| F22 dashboard XSS | INC-19 | — | output-escaping | G4 | `mcma/web` | Planned |
| F23 gitignore glob / session exclusion | INC-13 | — | vault-excluded-from-logs/git/backups | G3 | `mcma/portal` | Planned |
| F24 auth fail-open save | INC-13 | INC-16 | validated-store; no size-heuristic | G3 | `mcma/portal` | Planned |
| F25 page.pause in handler | INC-12 | INC-17 | async-jobs; READY terminal | G3 | `mcma/execution` | Planned |
| F26 logs-as-DB | INC-10 | — | sqlite-persistence | G3 | `mcma/persistence` | Planned |
| F27 demo-data-as-real | INC-19 | INC-14 | no-sample-default | G4 | `mcma/web` | Planned |
| F28 duplicated constants | INC-03 | — | single `mcma.core.config` | G1 | `mcma/core` | Planned |
| F29 silent excepts | INC-20 | — | no-silent-except-swallow | G-PDR | `mcma/core`,`mcma/app` | Planned |
| F30 menu preview no-op | INC-17 | INC-22 | proper endpoint; retired | G4 | `mcma/app` | Planned |
| F31 keeper no scheduling/escalation | INC-14 | INC-11, INC-20 | poller-under-lease-escalates | N/A | `mcma/notifications` | Planned |
| F32 screenshot name collisions | INC-20 | — | unique-names + retention | N/A | `mcma/core` | Planned |
| F33 keyword family inference | INC-04 | — | no-keyword-4-6/13-15 | G1 | `mcma/domain` | Planned |

## 3. ADRs (0001..0010)
| ADR | Primary | Supporting | Test/evidence | Gate | Target module | Status |
|---|---|---|---|---|---|---|
| 0001 modular monolith | INC-03 | — | import-linter contract | G1 | `mcma/*` | Planned |
| 0002 deterministic planning | INC-05 | INC-04 | plan_hash determinism | G1 | `mcma/planning` | Planned |
| 0003 read/write capability separation | INC-08 | INC-09 | capability safety tests | G2 | `mcma/portal` | Planned |
| 0004 network default-deny + final block | INC-07 | INC-23 | default-deny/final-abort | G2/G5 | `mcma/portal` | Planned |
| 0005 SQLite WAL + outbox | INC-10 | INC-15 | wal/outbox atomicity | G3 | `mcma/persistence` | Planned |
| 0006 claim identity + category presence | INC-10 | INC-14 | identity/presence | G3 | `mcma/persistence` | Planned |
| 0007 session vault + leases | INC-11 | INC-13 | leases/vault fail-closed | G3 | `mcma/persistence`,`mcma/portal` | Planned |
| 0008 API auth/authz + TLS | INC-16 | INC-17, INC-18 | auth/authz/TLS | G4 | `mcma/app` | Planned |
| 0009 SSE + delta recovery | INC-15 | INC-17 | replay/resync | G4 | `mcma/app`,`mcma/persistence` | Planned |
| 0010 incremental migration (meta) | INC-00 | INC-01..23 (whole roadmap) | gate sequence upheld | all gates | — | Planned |

## 4. Business rules (BUSINESS_RULES §B)
| Rule | Primary | Supporting | Test/evidence | Gate | Target module | Status |
|---|---|---|---|---|---|---|
| B.1 three-origin | INC-04 | — | three-origin 1/2/3 | G1 | `mcma/domain` | Planned |
| B.2 glass 19–24 | INC-04 | — | component×operation; fail-closed | G1 | `mcma/domain` | Planned |
| B.3 charge mutuelle native | INC-09 | INC-04, INC-12, INC-23 | never-directly-written + native-triggered + exact-summary-verified before readiness | G2/G5 | `mcma/portal`,`mcma/execution` | Planned |
| B.4 out-of-catalogue fail-closed | INC-04 | — | fail-closed | G1 | `mcma/domain` | Planned |
| B.5 mission identity two-tier | INC-09 | — | two-tier + registration mandatory | G2 | `mcma/portal` | Planned |
| B.6 negative TVA fail-closed | INC-04 | — | INVALID_TAX_ALLOCATION | G1 | `mcma/domain` | Planned |
| B.7 labour structured-first | INC-04 | — | structured-first; ambiguous fail-closed | G1 | `mcma/domain` | Planned |
| B.8 multi-account extensible | INC-10 | INC-11, INC-13, INC-17 | accounts registry; no hardcoded count | G3 | `mcma/persistence` | Planned |
| B.9 persistence identity | INC-10 | INC-14 | account_id+idSinistre | G3 | `mcma/persistence` | Planned |
| B.10 LAN security | INC-16 | INC-17, INC-18 | auth/authz/TLS/subnet | G4 | `mcma/app` | Planned |

## 5. Preserved recovery features (FEATURE_INVENTORY)
| Feature | Primary | Supporting | Test/evidence | Gate | Target module | Status |
|---|---|---|---|---|---|---|
| Manual login + OTP | INC-13 | INC-16 | onboarding tool + app auth | G3/G4 | `mcma/portal`,`mcma/app`,`tools/` | Planned |
| Session save/restore/validate; expiry detection | INC-13 | INC-14 | vault + validity checks | G3 | `mcma/portal` | Planned |
| Session keep-alive / refresh daemon | INC-14 | INC-11, INC-20 | poller under lease + escalation | N/A | `mcma/notifications` | Planned |
| Multi-account (Oujda/Nador) | INC-13 | INC-10, INC-11, INC-17 | vault + registry + per-account authz | G3/G4 | `mcma/portal`,`mcma/persistence` | Planned |
| Mission search / open | INC-09 | — | search exactly-one + open | G2 | `mcma/portal` | Planned |
| Mission identity verification | INC-09 | — | two-tier gate + TOCTOU | G2 | `mcma/portal` | Planned |
| Read dossier JSON + validate | INC-05 | INC-04 | typed input + fail-closed | G1 | `mcma/mapping`,`mcma/domain` | Planned |
| Form-fill / garage conventionné / row editing / native calc | INC-09 | INC-12 | RBW/DBW/VAW; native recalc | G2 | `mcma/portal` | Planned |
| Rubrique discovery & mapping | INC-04 | INC-05 | classification props | G1 | `mcma/domain` | Planned |
| Monetary calculation | INC-04 | — | Decimal + remainder allocation | G1 | `mcma/core`,`mcma/domain` | Preserved/re-asserted |
| Notification extraction | INC-14 | INC-08 | length=-1 + DOM fallback (fixtures) | N/A (prod via G-PDR) | `mcma/notifications` | Planned |
| Relance (read-only) | INC-14 | — | generic category, no mutation | N/A | `mcma/notifications` | Preserved/re-asserted |
| Dashboard | INC-19 | INC-15, INC-17 | escaping/CSP/readiness | G4 | `mcma/web` | Planned |
| FastAPI endpoints | INC-17 | INC-16 | typed routers + authz | G4 | `mcma/app` | Planned |
| SSE / live events | INC-15 | INC-17 | global-cursor + resync | G4 | `mcma/app`,`mcma/persistence` | Planned |
| Screenshots / diagnostics | INC-20 | — | unique names + retention + redaction | G-PDR | `mcma/core` | Planned |
| Readiness reports (truthful) | INC-12 | INC-19, INC-20 | real-check readiness | G3/G4 | `mcma/execution`,`mcma/web` | Planned |
| Windows launchers / employee startup | INC-18 | INC-00, INC-22 | TLS serve; old launchers retired | G4 | `deploy/` | Planned |
| Tests & fixtures | INC-01 | INC-02, all | egress lockdown + characterization | G0 | `tests/` | Planned |

## 6. Architecture requirements — the full 40-item matrix (correction #5)
Baseline class per Phase 3 `docs/architecture/TRACEABILITY_MATRIX.md` §1: **CC** compliant · **PC** partial · **CN**
noncompliant · **NI** not-implemented. Module paths are under `mcma/` (correction #4). Status = **Planned** unless the
baseline item is **CC** (Preserved/re-asserted).

| # | Requirement | Base | Primary | Supporting | Planned test | Gate | Target module | Status |
|---|---|---|---|---|---|---|---|---|
| 1 | Modular monolith boundaries | NI | INC-03 | — | import contract | G1 | `mcma/*` | Planned |
| 2 | Dependency rules between modules | CN | INC-03 | — | import-linter | G1 | `mcma/*` | Planned |
| 3 | Typed input & normalization | PC | INC-04 | INC-05 | property | G1 | `mcma/domain`,`mcma/mapping` | Planned |
| 4 | Workflow registry | NI | INC-05 | — | unit | G1 | `mcma/planning` | Planned |
| 5 | Typed execution plans (pure data) | NI | INC-05 | INC-04 | determinism | G1 | `mcma/planning`,`mcma/domain` | Planned |
| 6 | Deterministic planning | PC | INC-05 | INC-04 | `plan_hash` stable | G1 | `mcma/planning` | Planned |
| 7 | Separate read/write capabilities | CN | INC-08 | INC-09 | safety | G2 | `mcma/portal` | Planned |
| 8 | Dry-run technically write-incapable | CN | INC-08 | INC-09 | dry-run-no-writer | G2 | `mcma/portal` | Planned |
| 9 | Context-level network interception | CN | INC-07 | — | safety (context route) | G2 | `mcma/portal` | Planned |
| 10 | Default-deny write policy | CN | INC-07 | — | unknown→abort | G2 | `mcma/portal` | Planned |
| 11 | Permanent final-endpoint blocking | PC | INC-07 | INC-23 | final-abort | G2/G5 | `mcma/portal` | Planned |
| 12 | Explicit row-op allowlist | CN | INC-07 | INC-09, INC-23 | allowlist | G2 | `mcma/portal`,`mcma/planning` | Planned |
| 13 | Mission identity gate | CN | INC-09 | — | identity fail-closed | G2 | `mcma/portal` | Planned |
| 14 | Read-before-write | NI | INC-09 | INC-12 | integration | G2 | `mcma/portal`,`mcma/execution` | Planned |
| 15 | Diff-before-write | NI | INC-09 | INC-12 | integration | G2 | `mcma/portal`,`mcma/execution` | Planned |
| 16 | Verify-after-write | NI | INC-09 | INC-12 | integration | G2 | `mcma/portal`,`mcma/execution` | Planned |
| 17 | Fail-closed mapping | PC | INC-04 | INC-05, INC-09 | property (NeedsReview) | G1 | `mcma/domain` | Planned |
| 18 | Decimal monetary calculations | CC | INC-04 | — | property (money) | G1 | `mcma/core`,`mcma/domain` | Preserved/re-asserted |
| 19 | Native portal charge-mutuelle | CN | INC-09 | INC-04 | never-written | G2 | `mcma/portal`,`mcma/domain` | Planned |
| 20 | SQLite WAL persistence | NI | INC-10 | — | repo contract | G3 | `mcma/persistence` | Planned |
| 21 | Transactional event outbox | NI | INC-15 | INC-12 | outbox atomicity | G3 | `mcma/persistence` | Planned |
| 22 | Claim identity account_id+idSinistre | NI | INC-10 | INC-14 | uniqueness/NOT NULL | G3 | `mcma/persistence` | Planned |
| 23 | Separate category-presence history | NI | INC-10 | INC-14 | per-category presence | G3 | `mcma/persistence` | Planned |
| 24 | Complete-poll absence transitions | NI | INC-14 | INC-10 | three-poll-per-category | G-PDR | `mcma/notifications` | Planned |
| 25 | Monotonic state versions | NI | INC-10 | INC-15 | version | G3 | `mcma/persistence` | Planned |
| 26 | SSE with delta-query recovery | NI | INC-15 | INC-17 | replay/resync | G4 | `mcma/app`,`mcma/persistence` | Planned |
| 27 | Extensible account registry | NI | INC-10 | INC-13, INC-17 | accounts CRUD | G3 | `mcma/persistence` | Planned |
| 28 | Session-to-account binding | CN | INC-13 | INC-10 | binding fail-closed | G3 | `mcma/portal`,`mcma/persistence` | Planned |
| 29 | Per-account lock / lease | NI | INC-11 | INC-12 | lease acquire/fence | G3 | `mcma/persistence`,`mcma/execution` | Planned |
| 30 | Asynchronous automation jobs | CN | INC-12 | INC-17 | job lifecycle | G3 | `mcma/execution`,`mcma/app` | Planned |
| 31 | Server-side employee authentication | CN | INC-16 | — | auth | G4 | `mcma/app` | Planned |
| 32 | Role authorization | CN | INC-16 | INC-17 | RBAC | G4 | `mcma/app` | Planned |
| 33 | Secure session cookies & CSRF | CN | INC-16 | — | auth/CSRF | G4 | `mcma/app` | Planned |
| 34 | Server-derived audit identity | CN | INC-17 | INC-10 | audit | G4 | `mcma/app`,`mcma/persistence` | Planned |
| 35 | Separate view vs automation perms | CN | INC-16 | INC-17 | viewer-no-mutate | G4 | `mcma/app` | Planned |
| 36 | Configurable LAN exposure | CN | INC-18 | INC-00 | config; auth-not-disabled | G4 | `mcma/core`,`mcma/app` | Planned |
| 37 | Secret & PII protection | CN | INC-13 | INC-19, INC-20, INC-21 | vault/redaction/xss | G3/G-PDR | `mcma/portal`,`mcma/persistence` | Planned |
| 38 | Tests with unconditional prod-domain block | CN | INC-01 | INC-00 | socket-guard/proof | G0 | `tests/` | Planned |
| 39 | Observability without leaking data | CN | INC-20 | — | log-redaction | G-PDR | `mcma/core`,`mcma/app` | Planned |
| 40 | Deployment, migration & rollback | NI | INC-18 | INC-21, INC-22, INC-10 | migration+restore | G4/G5 | `deploy/`,`ops/` | Planned |

The three baseline **CC** items (18 Decimal money; INV-5 human-final-validation; INV-9 relance-not-mutated) are preserved
and re-asserted by tests in INC-04 / INC-12 / INC-14 respectively.

## 6a. Explicit Normal/PEC workflow contracts (traced separately)
| Item | Primary | Supporting | Test/evidence | Gate | Target module | Status |
|---|---|---|---|---|---|---|
| `RepairWorkflow` typed + `ProposedPlan.repair_workflow` in canonical serialization/`plan_hash`; two deterministic builders + registry names tested | INC-05 | INC-04 | plan-hash-includes-workflow; builder/registry tests | G1 | `mcma/domain`,`mcma/planning` | Planned |
| Mode Normal row persistence contract: `createRapportDefDet` (Ajouter lifecycle only; never used in PEC) | INC-09 | INC-06, INC-23 | complete-Normal-lifecycle mock test; cross-workflow use rejected | G2/G5 | `mcma/portal` | Planned |
| PEC row persistence contract: `updateDevisDet` (pencil lifecycle only; no Ajouter; all-row exact preflight before first mutation; never used in Normal) | INC-09 | INC-06, INC-23 | complete-PEC-lifecycle mock test; preflight fail-closed; cross-workflow use rejected | G2/G5 | `mcma/portal` | Planned |
| Workflow agreement: parent DRY_RUN/EXECUTE same `repair_workflow`; observed portal workflow == `ExecutablePlanData.repair_workflow` before any write; mismatch fails closed pre-mutation | INC-12 | INC-09 | workflow-mismatch rejection tests | G2/G3 | `mcma/execution`,`mcma/portal` | Planned |
| Mandatory native trigger + exact financial-summary verification in both workflows (Mode Normal native contract = G5 confirmation item) | INC-09 | INC-12, INC-23 | native-verification-mandatory; missing/stale/mismatch blocks readiness | G2/G5 | `mcma/portal`,`mcma/execution` | Planned |
| Deterministic VERIFYING failure: native calc failed/stale/missing or summary mismatch → `WRITE_ABORTED`; crash/restart in VERIFYING → `INTERRUPTED_NEEDS_HUMAN_REVIEW`, never auto-resumed | INC-12 | INC-09 | VERIFYING-failure + restart-reconciliation tests | G3 | `mcma/execution` | Planned |

## 7. Completeness statement
- **No orphans (proven by the fully-columned tables above):** §1 lists all 11 INV, §2 lists **F1..F33 individually**, §3
  all 10 ADRs, §4 all 10 business rules, §5 every preserved feature, and §6 all 40 architecture items — **each row carries
  exactly one primary increment, its supporting increments, a planned test/evidence, a blocking gate (or N/A), a target
  module, and a status.** The claim of no orphans rests on those explicit fields, not on a summary.
- **Duplicate work / shared dependencies:** INC-04 underpins INC-05/09 (rules); INC-10 underpins INC-11..21 (schema);
  INC-07 underpins INC-08/09 (interception); INC-13's DPAPI helper is reused by INC-12's `job_inputs` encryption (interface
  shared; INC-12 uses an injected encryptor stubbed until INC-13 lands).
- **Critical path (from the canonical dependency table in `REBUILD_ROADMAP.md`):**
  `INC-00 → INC-01 → INC-02 → INC-03 → INC-06 → INC-07 → INC-08 → INC-14 → INC-15 → INC-17 → INC-19 → INC-22 → INC-23`
  (13 increments; several equal-length paths exist). INC-09/INC-12/INC-13 are **parallel** branches (no direct edges
  between them) that reconverge only at INC-23 — the earlier linear `INC-09 → INC-12 → INC-13` claim was incorrect and is removed.
