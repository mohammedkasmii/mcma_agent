# Test Plan (cross-cutting)

Tests-first (TDD Iron Law). **No test may contact the live portal.** Runner: `python -m pytest` from repo root.
Layering follows `docs/architecture/TEST_STRATEGY.md`.

## 1. Existing tests that remain useful
- `tests/test_mapper.py` (12) — kept as characterization until INC-04 intentionally revises the defect-capturing cases
  (glass→1, `"mo"`), each with a recorded rationale.
- `tests/test_garage_conventionne.py` (5) — kept; the pure matcher is superseded by exact-`IdRubrique` selection (INC-09),
  and the matcher tests migrate to characterization.
- `tests/test_session_keeper.py` (2) — kept until the poller replaces the keeper (INC-11/14).

## 2. Characterization (INC-02, before refactor)
Golden tests for current mapper/garage/notification-shape from sanitized fixtures; defect-capturing goldens explicitly labeled.

## 3. Test categories → increment
| Category | Where proven |
|---|---|
| Baseline live-write containment (baseline write/API disabled during rebuild) | INC-00 (`test_baseline_fill_dossier_refuses_while_migration_mode`, `test_baseline_api_binds_loopback_only_while_migration_mode`) |
| Production-egress impossibility (subprocess + Chromium; no-emission preflight; sentinel target) | INC-01 (`test_egress_preflight_confirms_os_denial_without_emitting`, `test_subprocess_cannot_reach_sentinel_host`, `test_headless_chromium_cannot_reach_sentinel_host`) |
| Import/dependency contracts (pure modules, single owners) | INC-03 |
| Domain property tests (money, three-origin, glass, labour, normalize, negative-TVA fail-closed) | INC-04 |
| Plan determinism / purity / mandatory registration | INC-05 |
| Unknown request fails closed (GET not auto-safe) | INC-07 (`test_unknown_request_is_aborted`) |
| Final endpoints permanently blocked (abort, not fake-200) | INC-07 (`test_final_endpoints_abort_not_fulfilled`) |
| Dry-run cannot construct a writer | INC-08/INC-09 (`test_read_capability_cannot_be_upgraded_to_writer`, `test_dry_run_never_constructs_writer`) |
| Identity mismatch / zero-match / multiple-match | INC-09 |
| Exact-rubrique zero/multiple-match | INC-09 (`test_zero_or_multiple_rubrique_rows_fail_closed`) |
| Charge-mutuelle never written | INC-09 (`test_charge_mutuelle_fields_never_written`) |
| Decimal + negative-TVA | INC-04 (`test_negative_line_tva_fails_closed`) |
| Repository-contract + integrity (cross-account FK, NOT NULL idSinistre, status CHECK) | INC-10 |
| Single-writer + heartbeat-loss | INC-11 |
| Crash-recovery at every boundary (atomic enqueue; QUEUED/PLANNING/PLANNED re-plan; WRITING/VERIFYING never resume; exact ERROR reason codes) | INC-12 |
| Session-vault decryption/account-binding failure fail-closed | INC-13 |
| Category-scoped three-poll lifecycle | INC-14 |
| SSE cursor expiry / full resync / retention / authz revalidation | INC-15 |
| Auth (Argon2id, no default creds, CSRF, sessions) + secure bootstrap (loopback-only) | INC-16 |
| Cross-account authorization + server-derived audit + typed errors + no-mode / executions guards | INC-17 |
| TLS-only (refuse without cert; no HTTP listener) | INC-18 |
| Dashboard XSS removal + truthful readiness + no demo-as-real | INC-19 |
| Logging PII redaction + no silent excepts + audit hashes + real health | INC-20 |
| Backup/restore (online API) + at-rest gate | INC-21 |
| Feature parity + retired-paths-gone | INC-22 |
| Rollback returns to last-green (feature-flag flip / unmount) | INC-22 (`test_rollback_flag_flip_returns_to_last_green`) |
| Write-enable gate (confirmed contracts + green suite) + final still blocked | INC-23 |

## 4. Which tests use the extended mock server
INC-06 onward: INC-07/08/09 (interception, capabilities, writer), INC-14 (notification surface), integration tests in
INC-17/19. All bind loopback; CDN assets bundled/stubbed for air-gapped runs.

## 5. Which tests prove no live connection is possible
INC-01 proof tests (subprocess + Chromium) + the OS/CI egress denial (authoritative). Every browser test runs only under
this lockdown.

## 6. Property-based emphasis (Hypothesis)
Identifiers/registration normalization, mappings (origin/glass/labour), monetary/tax invariants, malformed inputs, plan
determinism, and job state-transition legality.

## 7. Crash-recovery test boundaries (INC-12)
Between: enqueue↔planning, planning↔authorization, authorization↔writing, writing↔verifying, verifying↔ready. Each asserts
the deterministic reconciliation outcome and that no partial write is auto-resumed.

## 8. Constraints
- No live portal contact anywhere. The real row-op contract confirmation (INC-23) is a supervised out-of-band step, never
  automated against production.
- Live form filling stays disabled in all tests until INC-23's gate logic; even then CI exercises only the **gate logic**,
  not a production write.
