# Phase 3 — Persistence & orchestration

---

## INC-10 — SQLite WAL + migration framework + repositories

- **Purpose/outcome:** Introduce the durable store (WAL, FK on, one writer) with a versioned migration framework and
  typed repositories for every table in `DATA_MODEL.md`.
- **Why here:** jobs, leases, vault, notifications, outbox, auth all persist here; it precedes them.
- **Prerequisites:** INC-03.
- **Addresses:** ADR-0005, ADR-0006; DATA_MODEL §1–§10; F26 (logs-as-DB).
- **Baseline files modified/retired:** none retired; the JSON-cache paths keep working until parity (INC-22).
- **Target modules/files introduced:** `persistence/db.py` (connection, WAL/PRAGMAs), `persistence/migrations/` (`0001_init.sql` … creating **all 20 DATA_MODEL tables**: accounts, **portal_sessions**, users, role_permissions, user_account_access, claims (`UNIQUE(account_id,portal_claim_id)` + `UNIQUE(account_id,claim_pk)`), categories, category_presence (composite FK to `claims(account_id,claim_pk)`), poll_runs, poll_run_categories, unmatched_notifications, account_state_version, event_outbox (global `AUTOINCREMENT` id), employee_actions, audit_events, automation_jobs (status CHECK), job_inputs, account_leases, observed_finalizations, schema_migrations), `persistence/repositories/*.py`. Tests under `tests/persistence/`.
  **Review SR-1 (was HIGH):** `portal_sessions` (DATA_MODEL §2) is included here — INC-13 depends on it; it must not be omitted.
  **Review SR-7:** migrations follow the **expand/contract** (compatibility-aware) discipline (DATA_MODEL §10); add `test_migration_is_expand_contract_compatible` (a new column is added nullable/defaulted before any code requires it).
- **DB migration impact:** creates the initial schema (forward migration `0001`).
- **Dependency/config impact:** stdlib `sqlite3` only (no new runtime dep). DB path from `core.config`, outside any served dir.
- **Feature flags/adapters:** the DB is created but not yet the authority for notifications/actions (dual-write/cutover is INC-14/22).
- **Out-of-scope:** business use of the tables (later increments).
- **Tests-first (repository-contract):**
  - `test_wal_enabled_and_foreign_keys_on`.
  - **`test_claim_requires_non_null_idSinistre`** and `test_claim_identity_unique_per_account`.
  - **`test_cross_account_category_presence_insert_fails`** (composite FK).
  - `test_unmatched_notifications_never_enter_claims`.
  - `test_automation_jobs_status_check_rejects_unknown_status`.
  - `test_migration_applies_forward_and_records_version`.
- **Initial failing-test expectation:** fail (schema/repos absent).
- **Mock/fixtures:** a temp SQLite file per test.
- **Implementation steps:** connection+PRAGMAs → migration runner + `0001` → repositories per aggregate → integrity tests.
- **Acceptance criteria:** schema matches DATA_MODEL exactly; all integrity tests green; migration forward+record works.
- **Safe offline verification:** `python -m pytest tests/persistence -v`.
- **Safety gates:** enabler for G3.
- **Expected git-diff scope:** `persistence/*`, `tests/persistence/*`.
- **Rollback:** delete `persistence/*`; no baseline dependency yet.
- **Risks/failure behavior:** integrity violations raise at the DB layer (fail-closed).
- **Subincrement split (correction #7):**
  - **INC-10A** — `mcma/persistence/db.py` (connection, WAL/`foreign_keys`/`busy_timeout`), the migration runner +
    `0001_init.sql` creating **all 20 tables**, `schema_migrations`; tests: WAL/FK on, all tables present, status CHECK,
    composite FK, NOT-NULL idSinistre, migration applies+records, expand/contract policy.
  - **INC-10B** — `mcma/persistence/repositories/*.py` (one per aggregate) with typed CRUD; tests: cross-account insert
    fails, unmatched-notifications staging, uniqueness, repository round-trips.
- **Definition of Done:** schema + integrity + migration tests green; DB outside served dir.
- **Approval boundary:** stop before INC-11.

---

## INC-11 — OS single-instance mutex + account leases + heartbeat-loss

- **Purpose/outcome:** Guarantee a single write-capable process (OS mutex) and provide per-account `LeaseHandle`s
  (acquire/heartbeat/expire) with a **heartbeat-loss → abort routing + close write context** response.
- **Why here:** jobs and the vault must coordinate account access before any write orchestration.
- **Prerequisites:** INC-10.
- **Addresses:** ADR-0007; SAFETY_MODEL §5; correction #5 (OS mutex authoritative; DB token is not external fencing).
- **Baseline files modified/retired:** none.
- **Target modules/files introduced:** `core/mutex.py` (Windows named mutex / single-instance), `persistence/leases.py`
  (`account_leases` acquire/renew/release; `LeaseHandle` impl), `execution/lease.py` (threads a real `LeaseHandle` into
  `portal` capabilities). Tests under `tests/persistence/leases/` + `tests/execution/`.
- **DB migration impact:** uses `account_leases` (already created in INC-10).
- **Dependency/config impact:** Windows API via `ctypes`/`pywin32` (dev/runtime, Windows-only) — justified; guard for non-Windows test runs with a portable fallback used only in tests.
- **Feature flags/adapters:** none.
- **Out-of-scope:** using the lease in jobs (INC-12) and vault (INC-13).
- **Tests-first:**
  - `test_second_process_cannot_acquire_write_capability` (OS mutex — simulated via the single-instance guard).
  - `test_lease_acquire_renew_expire`.
  - **`test_heartbeat_loss_aborts_routing_and_closes_write_context`** (portal writer given a lost lease → aborts).
  - `test_fencing_token_is_internal_only` (doc/behavior: writer stops on lost lease; not presented as portal-validated).
  - **`test_production_rejects_non_os_mutex`** (review SEC-4: production refuses to start with the portable/test mutex
    fallback; the OS single-instance mutex is the only production single-writer guarantee).
- **Initial failing-test expectation:** fail (modules absent).
- **Mock/fixtures:** temp DB; a stub portal write context to observe the abort/close on heartbeat loss.
- **Implementation steps:** OS mutex → lease table ops → LeaseHandle with heartbeat → wire heartbeat-loss into the writer's pre-write check.
- **Acceptance criteria:** single-writer enforced; heartbeat-loss aborts + closes; lease coordination across processes works.
- **Safe offline verification:** `python -m pytest tests/persistence/leases tests/execution -v`.
- **Safety gates:** contributes to **G3**.
- **Expected git-diff scope:** `core/mutex.py`, `persistence/leases.py`, `execution/lease.py`, tests.
- **Rollback:** delete the new modules.
- **Risks/failure behavior:** loss of lease ⇒ immediate write abort (fail-closed).
- **Definition of Done:** single-writer + heartbeat-loss tests green.
- **Approval boundary:** stop before INC-12.

---

## INC-12 — Durable job model: atomic enqueue, state machines, restart reconciliation

- **Purpose/outcome:** Implement `automation_jobs` + `job_inputs` with **atomic enqueue** (job + input + state-version +
  outbox in one tx), the **DRY_RUN** and **EXECUTE** state machines (structurally separate; EXECUTE re-checks
  input_hash/plan_hash; identity re-verified before writing), **idempotency**, and **deterministic restart reconciliation**
  with exact `ERROR` reason codes.
- **Why here:** the async execution engine; must precede API job endpoints and any live write.
- **Prerequisites:** INC-05 (plan), INC-10 (persistence), INC-11 (leases).
- **Addresses:** ADR-0002/0005; WORKFLOW_STATE_MODEL §2/§6/§7; **INV-5** (automation stops at `READY_FOR_HUMAN_REVIEW`;
  never finalizes; `FINALIZED_BY_HUMAN` is observed-only); correction #5; F25 (`page.pause` in handler → async jobs +
  READY_FOR_HUMAN_REVIEW).
- **Baseline files modified/retired:** none retired; baseline `process_workflow` (`main.py`) stays until INC-22.
- **Target modules/files introduced:** `execution/jobs.py` (enqueue, state machine, runner), `execution/inputs.py`
  (`job_inputs` encrypt/store/verify — encryption via the vault's DPAPI helper from INC-13, stubbed until then),
  `execution/reconcile.py` (restart). Tests under `tests/execution/jobs/`.
- **DB migration impact:** uses `automation_jobs`, `job_inputs`, `event_outbox`, `account_state_version` (INC-10).
- **Dependency/config impact:** none new (DPAPI arrives via INC-13; until then `job_inputs` uses an injected encryptor with a test stub).
  **Footgun guard (review SE-1):** the `job_inputs` encryptor is fail-closed — if the **production** DPAPI backend is
  unavailable, storing a job input **refuses** (job → `ERROR`), never falling back to a weak/test encryptor. The stub is
  selectable **only** in tests (enforced by a config guard); INC-12 must not run against production data before INC-13.
- **Feature flags/adapters:** EXECUTE runner performs writes only through the `VerifiedMissionWriter`, whose live-write
  path is still disabled (write-enable gate OFF). So EXECUTE against a live host cannot write.
- **Out-of-scope:** the API endpoints (INC-17); enabling live writes (INC-23).
- **Tests-first (repository + state + crash):**
  - **`test_atomic_enqueue_all_or_nothing`** (inject a failure in the tx → nothing committed).
  - `test_idempotent_resubmit_returns_existing_job`.
  - `test_dry_run_path_uses_read_capability_only`.
  - `test_execute_requires_dry_run_verified_parent_same_account_workflow`.
  - `test_execute_rechecks_input_hash_and_plan_hash` (mismatch → `INPUT_CHANGED`).
  - **restart — every non-terminal status has a deterministic, tested outcome (reviews SR-2..SR-5):**
    - `test_restart_queued_planning_planned_replans_deterministically` (→ back to `QUEUED`, re-plan).
    - **`test_restart_read_only_identity_check_returns_to_queued`** (DRY_RUN, read-only → re-plan; SR-4).
    - **`test_restart_acquiring_lock_identity_verifying_aborts_on_restart_and_releases_lease`** (pre-write; SR-2).
    - **`test_restart_identity_verified_aborts_on_restart_and_releases_lease`** (EXECUTE, lease held, still **pre-write** →
      `ABORTED_ON_RESTART` + release lease; SR-3 — see the architecture note below).
    - `test_restart_missing_input_errors_MISSING_JOB_INPUT`; `test_restart_expired_input_errors_INPUT_EXPIRED`;
      `test_restart_undecryptable_input_errors_INPUT_UNDECRYPTABLE`; `test_restart_hash_mismatch_errors_INPUT_HASH_MISMATCH`.
    - `test_restart_writing_verifying_never_auto_resumed` (→ `INTERRUPTED_NEEDS_HUMAN_REVIEW`).
    - **`test_restart_releases_stale_leases_first`** (`expires_at < now`; SR-5).
  - **`test_every_transition_writes_outbox_in_same_transaction`**.
  - **`test_readiness_terminal_at_ready_for_human_review`** (INV-5: the runner never transitions a job to a
    human-completed status; `FINALIZED_BY_HUMAN` is written only to `observed_finalizations`, never to `automation_jobs`).
- **Initial failing-test expectation:** all fail (modules absent).
- **Mock/fixtures:** temp DB; stub encryptor; stub portal writer.
- **Implementation steps:** atomic enqueue → state machine transitions (atomic + outbox) → idempotency → EXECUTE
  authorization checks → restart reconciliation with exact reason codes.
- **Acceptance criteria:** every WORKFLOW_STATE_MODEL §7 rule holds; restart is deterministic; WRITING/VERIFYING never
  auto-resume; atomic enqueue proven.
- **Safe offline verification:** `python -m pytest tests/execution/jobs -v`.
- **Safety gates:** **G3** (with INC-11, INC-13).
- **Expected git-diff scope:** `execution/*`, `tests/execution/jobs/`.
- **Rollback:** delete `execution/jobs.py` etc.; baseline workflow untouched.
- **Risks/failure behavior:** any crash-recovery ambiguity resolves fail-closed (`ERROR`/`INTERRUPTED_NEEDS_HUMAN_REVIEW`).
- **Subincrement split (correction #7):**
  - **INC-12A** — `mcma/execution/inputs.py` + atomic **enqueue** (`automation_jobs` QUEUED + `job_inputs` +
    state-version + outbox in one tx) + idempotency + the status-CHECK contract; tests: atomic-all-or-nothing,
    idempotent-resubmit, fail-closed encryptor.
  - **INC-12B** — `mcma/execution/jobs.py` (DRY_RUN + EXECUTE state machines; EXECUTE authorization + hash re-check) and
    `mcma/execution/reconcile.py` (deterministic restart, all reason codes, INV-5 terminal); tests: the full state +
    restart + INV-5 set listed above.
- **Definition of Done:** state/crash tests green; atomic enqueue proven.
- **Approval boundary:** stop before INC-13.

---

## INC-13 — Multi-account session vault: DPAPI handoff, rotation, revocation, fail-closed

- **Purpose/outcome:** Implement the session vault: **DPAPI LocalMachine + service-account-only NTFS ACL**; the desktop
  onboarding tool produces **in-memory** material and hands it to the **service** via an authenticated single-use
  account-bound handoff; the service acquires the account lease, validates identity evidence, encrypts and **atomically**
  stores; rotation/revocation; **decryption/binding failure fails closed**.
- **Why here:** real sessions are required for any live portal use; write jobs require positive identity.
- **Prerequisites:** INC-10, INC-11.
- **Addresses:** ADR-0007; SAFETY_MODEL §7; INV-10; F21 (plaintext session), F23 (gitignore glob), F24 (auth fail-open save).
- **Baseline files modified/retired:** none retired; baseline `auth_setup.py` stays until INC-22 (its fail-open save is
  replaced by the validated store here).
- **Target modules/files introduced:** `portal/vault.py` (DPAPI encrypt/decrypt, atomic store, rotation/revocation),
  `app/onboarding.py` (one-time local token endpoint; **no server-side browser launch**), a standalone desktop tool
  `tools/onboarding_tool.py` (headed `LoginCapability`, in-memory handoff). Tests under `tests/portal/vault/`.
- **DB migration impact:** uses `portal_sessions` (INC-10).
- **Dependency/config impact:** DPAPI via `pywin32`/`ctypes` (Windows). Non-Windows CI uses an injected crypto backend
  **only in tests** (never a production fallback that weakens protection).
- **Feature flags/adapters:** the DPAPI backend is injected; production is LocalMachine+ACL, tests use an in-memory backend.
  **Footgun guard (review SE-3):** the in-memory/portable crypto and lease/mutex backends are **test-only** and are not
  importable or selectable in production (enforced by a config/startup guard); there is no production fallback that
  weakens at-rest protection or single-writer guarantees.
- **Out-of-scope:** enabling live writes (INC-23).
- **Tests-first:**
  - **`test_decryption_failure_fails_closed`** (no read/write proceeds).
  - **`test_account_binding_mismatch_fails_closed`** (opened portal identity ≠ account → fail closed for write jobs).
  - `test_atomic_replacement_no_partial_session`.
  - `test_rotation_and_revocation_force_relogin`.
  - `test_onboarding_tool_never_writes_plaintext_or_vault_dir` and `test_service_acquires_lease_before_session_replace`.
  - `test_sessions_login_endpoint_does_not_launch_server_browser`.
  - **`test_production_config_rejects_non_dpapi_backend`** (review SEC-4: production refuses the in-memory/test crypto backend).
  - **`test_store_refuses_when_service_account_only_acl_cannot_be_set`** (review SEC-5: the restrictive NTFS ACL is a
    **hard, verified** precondition — LocalMachine DPAPI ciphertext is decryptable by any local user, so if the
    service-account-only ACL cannot be applied and verified, the store **aborts** rather than persist the session).
- **Initial failing-test expectation:** all fail (modules absent).
- **Mock/fixtures:** in-memory crypto backend (test-only); on Windows CI, a temp vault dir with the restrictive NTFS ACL
  **applied and asserted** (the ACL is a hard precondition, not "where feasible" — see Risks).
- **Implementation steps:** DPAPI encrypt/decrypt (injected backend) → atomic store → in-memory handoff protocol →
  service validation + lease-before-replace → rotation/revocation → fail-closed paths.
- **Acceptance criteria:** all vault safety tests green; plaintext never on disk; write jobs require positive identity.
- **Safe offline verification:** `python -m pytest tests/portal/vault -v`.
- **Safety gates:** **G3** (phase gate) — with INC-11/12.
- **Expected git-diff scope:** `portal/vault.py`, `app/onboarding.py`, `tools/onboarding_tool.py`, tests.
- **Rollback:** delete the new vault modules; baseline `auth_setup.py` still functions (though fail-open) until parity.
- **Risks/failure behavior:** any decrypt/binding failure ⇒ fail closed. DPAPI scope must match the service account
  (documented; a mismatch is caught by the decryption-failure test on the real host). **The service-account-only NTFS ACL
  is the sole confidentiality control for LocalMachine DPAPI and is therefore a HARD precondition (SEC-5): the vault
  refuses to persist a session if that ACL cannot be set and verified** — not "where feasible".
- **Subincrement split (correction #7):**
  - **INC-13A** — `mcma/portal/vault.py`: DPAPI LocalMachine encrypt/decrypt (injected backend), atomic store, **hard
    NTFS-ACL precondition**, rotation/revocation, decrypt/binding fail-closed; tests: decrypt-fail, binding-mismatch,
    atomic-replace, ACL-precondition, prod-rejects-non-DPAPI.
  - **INC-13B** — `mcma/app/onboarding.py` (one-time local token, no server browser) + `tools/onboarding_tool.py`
    (headed LoginCapability, in-memory handoff) + service validation + **lease-before-replace**; tests: no-plaintext/
    vault write by tool, lease-before-replace, sessions-login-no-server-browser.
- **Definition of Done:** vault safety tests green; **Gate 3 review** ready.
- **Approval boundary:** stop; **Gate 3 review** before Phase 4.
