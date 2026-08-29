# Traceability & Backlog Completeness

Every safety invariant, known failure, ADR, business rule, preserved feature, and architecture-noncompliance item maps
to **exactly one primary increment** (plus supporting increments). Nothing from Phase 3 disappears silently.

## 1. Safety invariants (INV-1..INV-11)
| INV | Primary | Supporting | Test | Gate |
|---|---|---|---|---|
| INV-1 dry-run write-incapable | INC-08 | INC-09 | dry-run-has-no-writer | G2 |
| INV-2 mission identity | INC-09 | — | identity mismatch/zero/multiple | G2 |
| INV-3 default-deny interception | INC-07 | — | unknown-request-aborts | G2 |
| INV-4 final endpoints blocked | INC-07 | INC-23 | final-abort-not-fake200 | G2/G5 |
| INV-5 human final validation | INC-12 | INC-23 | READY_FOR_HUMAN_REVIEW terminal | G3/G5 |
| INV-6 fail-closed mapping (+exact rubrique) | INC-04 | INC-05, INC-09 | fail-closed props; exact-IdRubrique | G1/G2 |
| INV-7 Decimal, no negative TVA | INC-04 | — | negative-TVA-fails-closed | G1 |
| INV-8 charge-mutuelle native-only | INC-09 | — | charge-mutuelle-never-written | G2 |
| INV-9 relance not mutated | INC-14 | — | extraction-read-only | — |
| INV-10 secrets/PII | INC-13 | INC-19, INC-20, INC-21 | vault/logs/xss/at-rest | G3 |
| INV-11 API authn / no LAN exposure | INC-16 | INC-17, INC-18 | auth/authz/TLS | G4 |

## 2. Known failures (F1..F33)
| F | Increment(s) |
|---|---|
| F1,F2,F10 preview/unblocked row endpoints | INC-07, INC-08, INC-09, INC-23 |
| F3,F4,F5 wrong-mission selection/identity | INC-09 |
| F6 forced charge-mutuelle | INC-09 (retire INC-22) |
| F7 duplicate checkmark | INC-09 |
| F8 fail-open interceptor | INC-07 |
| F9 page-scoped interception | INC-07 |
| F11 mapping_status unused | INC-05 |
| F12 false READY/Prêt | INC-19 (workflow INC-12) |
| F13 glass→1 | INC-04 |
| F14 out-of-catalogue default | INC-04 |
| F15 `"mo"` token | INC-04 |
| F16 rubrique-row selection | INC-09 |
| F17 negative TVA | INC-04 |
| F18 unauth LAN API | INC-16, INC-17, INC-18 |
| F19 error leakage | INC-17 |
| F20 200-on-failure | INC-17 |
| F21 PII in logs | INC-20 (vault INC-13) |
| F22 XSS | INC-19 |
| F23 gitignore glob / session material exclusion | INC-13 (+ config) |
| F24 auth fail-open save | INC-13, INC-16 |
| F25 page.pause in handler | INC-12 |
| F26 logs-as-DB | INC-10 |
| F27 demo-as-real | INC-19 |
| F28 duplicated constants | INC-03 |
| F29 silent excepts | INC-20 |
| F30 menu preview no-op | INC-17 (proper endpoint), retire INC-22 |
| F31 keeper no escalation | INC-14 (session-refresh poller under lease — primary), INC-11 (lease), INC-20 (escalation via health) |
| F32 screenshot collisions | INC-20 |
| F33 keyword family inference | INC-04 |

## 3. ADRs
| ADR | Increment(s) |
|---|---|
| 0001 modular monolith | INC-03 |
| 0002 deterministic planning | INC-04, INC-05 |
| 0003 read/write capability separation | INC-08, INC-09 |
| 0004 network default-deny + final block | INC-07 (write-enable INC-23) |
| 0005 SQLite WAL + outbox | INC-10, INC-15 |
| 0006 claim identity + category presence | INC-10, INC-14 |
| 0007 session vault + leases | INC-11, INC-13 |
| 0008 API auth/authz + TLS | INC-16, INC-17, INC-18 |
| 0009 SSE + delta recovery | INC-15 |
| 0010 incremental migration | whole roadmap (INC-01..23) |

## 4. Business rules (BUSINESS_RULES §B)
| Rule | Increment |
|---|---|
| B.1 three-origin | INC-04 |
| B.2 glass 19–24 | INC-04 |
| B.3 charge mutuelle native | INC-09 |
| B.4 out-of-catalogue fail-closed | INC-04 |
| B.5 mission identity two-tier | INC-09 |
| B.6 negative TVA fail-closed | INC-04 |
| B.7 labour structured-first | INC-04 |
| B.8 multi-account extensible | INC-10 (accounts registry schema), INC-11, INC-13, INC-17 |
| B.9 persistence identity | INC-10, INC-14 |
| B.10 LAN security | INC-16, INC-17, INC-18 |

## 5. Preserved recovery features (FEATURE_INVENTORY)
| Feature | Increment |
|---|---|
| Manual login + OTP | INC-13 (tool), INC-16 (app auth) |
| Session save/restore/validate; expiry detection | INC-13, INC-14 |
| Session keep-alive / refresh daemon | INC-14 (session-refresh poller under lease — primary), INC-11, INC-20 |
| Multi-account (Oujda/Nador) | INC-11, INC-13, INC-17 |
| Mission search / open | INC-09 |
| Mission identity verification | INC-09 |
| Read dossier JSON + validate | INC-05 |
| Form-fill (normal) / garage conventionné / row editing / native calc | INC-09 |
| Rubrique discovery & mapping | INC-04, INC-05 |
| Monetary calculation | INC-04 |
| Notification extraction | INC-14 |
| Relance (read-only) | INC-14 |
| Dashboard | INC-19 |
| FastAPI endpoints | INC-16, INC-17 |
| SSE / live events | INC-15 |
| Screenshots / diagnostics | INC-20 |
| Readiness reports (truthful) | INC-12, INC-19, INC-20 |
| Windows launchers / employee startup | INC-18 (TLS serve), INC-22 (retire old) |
| Tests & fixtures | INC-01, INC-02, all |

## 6. Architecture-noncompliance items (TRACEABILITY_MATRIX §1 — the 40 items)
Every item classified `CN`/`PC`/`NI` at baseline maps to a primary increment above (safety items → INC-04..09; data →
INC-10..15; API/auth → INC-16..18; ops/observability/deploy → INC-20/21/18; the write-enable gate → INC-23). The `CC`
items (Decimal money, human-final-validation, relance-not-mutated) are preserved and re-asserted by tests in INC-04/12/14.

## 7. Completeness statement
- **No orphans:** every INV, every F1..F33, every ADR, every business rule, every preserved feature, and every
  noncompliant architecture item has a primary increment and a planned test.
- **Duplicate work / shared dependencies:** INC-04 underpins INC-05/09 (rules); INC-10 underpins INC-11..21 (schema);
  INC-07 underpins INC-08/09 (interception); INC-13's DPAPI helper is reused by INC-12's `job_inputs` encryption (interface
  shared; INC-12 uses an injected encryptor stubbed until INC-13 lands).
- **Critical path:** INC-01 → INC-03 → INC-04 → INC-05 → INC-09 → INC-12 → INC-13 → INC-23 (the live-write gate).
