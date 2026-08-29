# TRACEABILITY MATRIX

**Baseline (production code):** `0290fe9df24c9e2f2b054ee4f8b14b8267f07b12` · **Design target:** this `docs/architecture/` set.

Each required item maps to its target module, document, ADR and planned test, plus a **baseline compliance
classification** (decision #7). Classification legend — evaluated against the code at baseline `0290fe9`:
**CC** CURRENTLY_COMPLIANT · **CN** CURRENTLY_NONCOMPLIANT · **PC** PARTIALLY_COMPLIANT · **NI** NOT_IMPLEMENTED · **NA** NOT_APPLICABLE.
Baseline noncompliance is **expected** — it is the Phase 4 migration backlog, not an architecture contradiction.

---

## 1. The 40 required architecture items
| # | Requirement | Module | Doc | ADR | Planned test | Baseline |
|---|---|---|---|---|---|---|
| 1 | Modular monolith boundaries | all | MODULE_BOUNDARIES | 0001 | import-linter contract | NI |
| 2 | Dependency rules between modules | all | MODULE_BOUNDARIES | 0001 | import-linter contract | CN |
| 3 | Typed input & normalization contracts | domain,mapping | DOMAIN_MODEL | 0002 | property tests | PC |
| 4 | Workflow registry | planning | WORKFLOW_STATE_MODEL | 0002 | unit | NI |
| 5 | Typed execution plans | planning,domain | DOMAIN_MODEL | 0002 | property (determinism) | NI |
| 6 | Deterministic planning | planning | DOMAIN_MODEL,WORKFLOW_STATE_MODEL | 0002 | plan_hash determinism | PC |
| 7 | Separate read & write capabilities | portal | SAFETY_MODEL | 0003 | safety tests | CN |
| 8 | Dry-run technically write-incapable | portal,execution | SAFETY_MODEL | 0003 | dry-run-has-no-writer | CN |
| 9 | Context-level network interception | portal | SAFETY_MODEL | 0004 | safety (context route) | CN |
| 10 | Default-deny write policy | portal | SAFETY_MODEL | 0004 | safety (unknown→abort) | CN |
| 11 | Permanent final-endpoint blocking | portal | SAFETY_MODEL | 0004 | safety (final abort) | PC |
| 12 | Explicit allowlist for row ops | portal,planning | SAFETY_MODEL | 0004 | safety (allowlist) | CN |
| 13 | Mission identity gate | portal | SAFETY_MODEL | 0003 | identity property | CN |
| 14 | Read-before-write | execution | WORKFLOW_STATE_MODEL | 0003 | integration | NI |
| 15 | Diff-before-write | execution | WORKFLOW_STATE_MODEL | 0003 | integration | NI |
| 16 | Verify-after-write | execution | WORKFLOW_STATE_MODEL | 0003 | integration | NI |
| 17 | Fail-closed mapping | domain,mapping | DOMAIN_MODEL | 0002 | property (NeedsReview) | PC |
| 18 | Decimal monetary calculations | domain | DOMAIN_MODEL | 0002 | property (money) | CC |
| 19 | Native portal charge-mutuelle | domain,portal | SAFETY_MODEL,DOMAIN_MODEL | 0002 | safety (never-written) | CN |
| 20 | SQLite WAL persistence | persistence | DATA_MODEL | 0005 | repo contract | NI |
| 21 | Transactional event outbox | persistence | DATA_MODEL | 0005 | outbox atomicity | NI |
| 22 | Claim identity account_id+idSinistre | persistence,domain | DATA_MODEL | 0006 | uniqueness/NOT NULL | NI |
| 23 | Separate category-presence history | persistence | DATA_MODEL | 0006 | presence tests | NI |
| 24 | Complete-poll absence transitions | notifications,persistence | DATA_MODEL | 0006 | three-poll test | NI |
| 25 | Monotonic state versions | persistence | DATA_MODEL | 0005/0009 | version test | NI |
| 26 | SSE with delta-query recovery | app,persistence | API_CONTRACTS,DATA_MODEL | 0009 | SSE replay/resync | NI |
| 27 | Extensible account registry | persistence | DATA_MODEL | 0007 | accounts CRUD | NI |
| 28 | Session-to-account binding | portal,persistence | SAFETY_MODEL,DATA_MODEL | 0007 | binding fail-closed | CN |
| 29 | Per-account asyncio lock / lease | execution,persistence | DATA_MODEL,WORKFLOW_STATE_MODEL | 0007 | lease acquire/fence | NI |
| 30 | Asynchronous automation jobs | app,execution | API_CONTRACTS,WORKFLOW_STATE_MODEL | 0002 | job lifecycle | CN |
| 31 | Server-side employee authentication | app | API_CONTRACTS | 0008 | auth tests | CN |
| 32 | Role authorization | app | API_CONTRACTS | 0008 | RBAC tests | CN |
| 33 | Secure session cookies & CSRF | app | API_CONTRACTS | 0008 | auth/CSRF tests | CN |
| 34 | Server-derived audit identity | app,persistence | API_CONTRACTS,DATA_MODEL | 0008 | audit test | CN |
| 35 | Separate view vs automation permissions | app | API_CONTRACTS | 0008 | RBAC (viewer no-mutate) | CN |
| 36 | Configurable LAN exposure | core,app | API_CONTRACTS | 0008 | config test | CN |
| 37 | Secret & PII protection | all | DATA_MODEL,SAFETY_MODEL,THREAT_MODEL | 0005/0007 | redaction/vault tests | CN |
| 38 | Tests with unconditional prod-domain block | tests | TEST_STRATEGY | 0010 | socket-guard test | CN |
| 39 | Observability without leaking data | core,app | ARCHITECTURE,THREAT_MODEL | 0008 | log-redaction test | CN |
| 40 | Deployment, migration & rollback | ops | ARCHITECTURE,DATA_MODEL | 0005/0010 | migration+restore test | NI |

## 2. Safety invariants (recovery INV-1..11)
| Invariant | Enforced by | ADR | Baseline |
|---|---|---|---|
| INV-1 dry-run write-incapable | SAFETY_MODEL §1-2 | 0003 | CN |
| INV-2 mission identity | SAFETY_MODEL §4 | 0003 | CN |
| INV-3 default-deny fail-closed interception | SAFETY_MODEL §3 | 0004 | CN |
| INV-4 final endpoints permanently blocked | SAFETY_MODEL §3 | 0004 | PC |
| INV-5 human final validation | WORKFLOW_STATE_MODEL §6 | 0002 | CC |
| INV-6 three-origin fail-closed mapping | DOMAIN_MODEL | 0002 | PC |
| INV-7 Decimal, no negative TVA | DOMAIN_MODEL §5 | 0002 | PC |
| INV-8 charge-mutuelle native-only | SAFETY_MODEL §6 | 0002 | CN |
| INV-9 relance not mutated | (no write contract) | 0004 | CC |
| INV-10 secrets/PII not exposed | DATA_MODEL §9, SAFETY_MODEL §7 | 0005/0007 | CN |
| INV-11 API authn / no LAN exposure | API_CONTRACTS | 0008 | CN |

## 3. Known failures (recovery F1..F33) — resolution target
| Finding(s) | Resolved by | Baseline |
|---|---|---|
| F1,F2,F10 preview writes / unblocked row endpoints | capability separation + allowlist (0003/0004) | CN |
| F3,F4,F5 wrong-mission selection/identity | identity gate (0003) | CN |
| F6 forced charge-mutuelle | native-only (0002) | CN |
| F7 duplicate checkmark | single explicit write_row + verify | CN |
| F8 fail-open interceptor | abort not fake-200 (0004) | CN |
| F9 page-scoped interception | context-level route (0004) | CN |
| F11 mapping_status unused | plan NeedsReview blocks writes (0002) | CN |
| F13,F14,F15,F33 mapping defaults | fail-closed mapping (0002) | CN/PC |
| F17 negative TVA | INVALID_TAX_ALLOCATION (0002) | CN |
| F18,F19,F20 LAN API / error leakage / 200-on-failure | auth+TLS+typed errors (0008) | CN |
| F21,F22,F23 PII logs / XSS / gitignore glob | vault+redaction+encoding (0005/0007/0008) | CN |
| F24 auth fail-open save | login capability + validated save | CN |
| F25 page.pause in handler | async jobs + READY_FOR_HUMAN_REVIEW (0002) | CN |
| F26 logs-as-DB | SQLite persistence (0005) | CN |
| F27 demo data as real | remove/clearly-mark sample data | CN |
| F28 duplicated constants | single core.config | CN |
| F29 silent excepts | typed errors + logging | CN |
| F30 menu preview no-op | proper CLI/endpoint | CN |
| F31 keeper no escalation | poller under lease + health | CN |
| F32 screenshot name collisions | unique names + retention | CN |

## 4. Resolved decisions (recovery R1..R14 + Phase 3 finals)
Three-origin (R1), glass 19–24 vocab (R2/#1), charge-mutuelle native (R3/#3-plan), out-of-catalogue fail-closed (R4),
identity two-tier (R5/#2), negative-TVA fail-closed (R6/#4-plan), labour structured-first (R7/#3-plan), persistence
identity (R8), LAN security (R9), multi-account (R10), INV-4 reclassification (R11), canonical route (R12), plan-file
(R13), cross-branch exclusion (R14); Phase-3 finals #1–#8 (TLS, auth, at-rest, DPAPI, leases, SSE retention, spec-to-code
classification, human finalization). All are reflected in the documents cited above with no contradiction to the recovery baseline.
