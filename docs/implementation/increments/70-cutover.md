# Phase 7 — Cutover, retirement & the write-enable gate

---

## INC-22 — Feature-parity verification + retire obsolete baseline paths

- **Purpose/outcome:** Prove the new system reaches **feature parity** for every preserved feature, then **retire** the
  defective baseline paths — only after parity is demonstrated.
- **Why here:** obsolete paths (unauth API, forced charge-mutuelle, logs-as-DB, duplicated constants, fail-open
  interceptor, fail-open auth save, no-op menu preview) must not linger once replaced; but never removed before parity.
- **Prerequisites:** INC-14, INC-17, INC-19, INC-20, INC-21
- **Prerequisite rationale:** all replacements exist and are proven, incl. backup/at-rest (INC-21) before retiring baseline persistence paths.
- **Addresses:** "preserve every working feature" + safe replacement; F6, F8, F12, F24, F26, F28, F30; retirement of
  `browser/safety_interceptor.py` (old), `browser/mode_normal.py` charge-mutuelle force, `main.py` unauth API + `process_workflow`, `core/logger.py`, `menu.py` preview, `auth_setup.py` fail-open save, duplicated constants.
- **Baseline files modified/retired:** the above baseline files are removed/replaced **after** parity tests pass. This is
  the first increment that deletes baseline production code.
- **Target modules/files introduced:** `tests/parity/*` (feature-parity suite mapping each preserved feature to a new-vs-old
  equivalence or an intentional-improvement assertion); deletions of the retired files.
- **DB migration impact:** may add a migration to drop any transitional JSON-compat shims.
- **Dependency/config impact:** remove now-unused deps if any (e.g., if PDF compression is truly gone).
- **Feature flags/adapters:** flip the dashboard/notification read flags to DB-backed permanently; remove legacy flags.
- **Out-of-scope:** enabling live writes (INC-23).
- **Tests-first:** a parity assertion per preserved feature (auth/session, notifications extraction, dashboard tracking,
  mapping outputs vs the INC-04 corrected goldens, session keep-alive/refresh → poller); **`test_retired_paths_are_gone`**
  (imports of removed modules fail); `test_no_forced_charge_mutuelle_path_remains`; **`test_rollback_flag_flip_returns_to_last_green`**
  (review AR-M4: flipping a feature flag / unmounting the new app returns the system to its previous green state — the
  documented `ROLLBACK_PLAN.md` flip-back paths are exercised, not just described).
- **Initial failing-test expectation:** parity tests fail until parity is real; retirement tests fail until deletions land.
- **Mock/fixtures:** the extended mock server + fixtures.
- **Implementation steps:** prove parity → delete retired files → update references → re-run full suite.
- **Acceptance criteria:** parity proven; retired paths gone; full offline suite green; **no live write enabled**.
- **Safe offline verification:** `python -m pytest -v` (whole suite, offline).
- **Safety gates:** parity gate; must not regress G0–G4.
- **Expected git-diff scope:** deletions of retired baseline files + `tests/parity/*` + reference updates.
- **Rollback:** redeploy the **last tested, tagged, post-INC-00 contained release** (read-only) and, if a specific
  preserved feature regressed, restore **only the explicitly identified safe/read-only compatibility code** for that
  feature from the contained state. **Never** restore the retired baseline *writer* and **never** re-enable a legacy write
  flag — those were permanently removed at INC-00. The production baseline `0290fe9` is **historical/reference evidence
  only**, never an operational rollback target.
- **Risks/failure behavior:** if parity is not fully proven for a feature, that feature's baseline path is **kept** (not deleted) and flagged for a follow-up increment.
- **Subincrement split (correction #7):**
  - **INC-22A** — (i) the **feature-parity suite** proving every preserved feature (new-vs-old equivalence or documented
    improvement, no deletions yet), and (ii) **supervised production notification-ingestion activation** (correction #2):
    - **Owner/precondition:** activation is available **only after** INC-14, INC-20, INC-21 **and G-PDR** have passed; it
      **defaults unavailable** before the gate.
    - **Approval requirement:** explicit owner sign-off, recorded, before the first production ingestion.
    - **Evidence:** the G-PDR checklist artifacts (DB outside served dir; BitLocker/SQLCipher; verified NTFS ACL;
      verified encrypted-backup destination; PII-safe logging + screenshot proof).
    - **Tests:** `test_production_ingestion_unavailable_before_g_pdr`; `test_production_ingestion_requires_owner_approval`;
      `test_ingestion_rollback_returns_to_synthetic_without_deleting_evidence`.
    - **Rollback:** **disable production ingestion and return to synthetic/mock data** without deleting any already-retained
      evidence/records.
    - **Definition of Done:** parity green; activation gated on G-PDR + approval; rollback proven to fall back to synthetic
      data with retained evidence intact.
    - Gate: parity + G-PDR + approval must all hold before 22B.
  - **INC-22B** — **retire** the baseline paths (delete the retired files, update references), **tighten the import
    contract** (remove the legacy allowlist so the final ownership rule applies with no exceptions), flip read flags to
    DB-backed permanently, and prove rollback (`test_rollback_flag_flip_returns_to_last_green`) — never restoring the
    unsafe writer.
- **Definition of Done:** parity suite green; retirements landed; import contract tightened; full suite green offline.
- **Approval boundary:** stop before INC-23.

---

## INC-23 — Endpoint-contract confirmation + write-enable gate + canary cutover

- **Purpose/outcome:** The **only** increment that may permit a live row write. Confirm the **real** portal write
  contracts against approved safe evidence / a captured mock-contract, satisfy the write-enable gate (confirmed contract
  records **and** all safety tests green), then perform a controlled **canary** with human final validation still mandatory.
- **Why here:** it is the terminal safety gate; everything upstream converges here (critical path endpoint).
- **Prerequisites:** INC-09, INC-12, INC-13, INC-18, INC-22
- **Prerequisite rationale:** the writer (INC-09), jobs (INC-12), vault (INC-13), TLS (INC-18), and parity+retirement (INC-22).
- **Addresses:** ADR-0004 (A5 write-enable gate); INV-1..INV-8 (all write-safety invariants must be verified); the
  master-prompt rule that endpoint names in the baseline do **not** authorize writes.
- **Baseline files modified/retired:** none (baseline already retired at INC-22).
- **Target modules/files introduced:** `portal/contracts/confirmed_row_ops.py` (the confirmed, reviewed row-op contract
  records — populated only from approved evidence), `deploy/canary.md` (on-site verification + rollback), `tests/portal/writeenable/`.
- **DB migration impact:** none.
- **Dependency/config impact:** none.
- **Feature flags/adapters (review SEC-7 — runtime control is data-driven, not a stored boolean):** the **runtime**
  write-enable condition is the presence of **`confirmed_row_ops` contract records** populated **only** from approved
  evidence; a live write targets only a confirmed contract. Condition **(b) "full safety suite green" is a CI/release
  precondition** enforced in the pipeline — **not** a runtime flag the service reads. Staleness of (b) is prevented by
  binding the green-suite evidence to the **same commit** that populates `confirmed_row_ops` (a record from a different
  commit is invalid). No hand-set "tests_passed" boolean can satisfy the gate.
- **Out-of-scope:** any final portal action — the agent still never invokes Enregistrer/Valider/Clôture/GED; a job's
  terminal automation state is `READY_FOR_HUMAN_REVIEW`.
- **Tests-first:** **`test_write_enable_requires_confirmed_contracts_and_green_safety_suite`**;
  `test_write_targets_only_confirmed_row_op_contracts`; `test_final_endpoints_still_permanently_blocked_with_writes_enabled`;
  `test_canary_write_produces_readiness_report_and_stops_at_human_review`.
- **Initial failing-test expectation:** fail (gate + confirmed contracts absent).
- **Mock/fixtures:** the mock server stands in for the portal during automated tests; the **real** contract confirmation
  is an approved, human-supervised, out-of-band step recorded in `deploy/canary.md` — never automated against production
  in the test suite.
- **Implementation steps:** confirm contracts from approved evidence → populate `confirmed_row_ops` → satisfy the
  write-enable gate → run a single supervised canary → verify readiness report → stop at human review.
- **Acceptance criteria:** live write occurs **only** for confirmed contracts, only under the gate, with final endpoints
  still blocked and human final validation mandatory; a documented rollback exists.
- **Safe offline verification:** `python -m pytest tests/portal/writeenable -v` (offline gate logic; the live canary is a
  supervised on-site procedure, not part of CI).
- **Safety gates:** **G5 — the live-write gate.** No live write before this passes with explicit owner approval.
- **Expected git-diff scope:** `portal/contracts/*`, `deploy/canary.md`, tests.
- **Rollback:** **revoke/expire the approved portal-contract record** (`confirmed_row_ops`), **close the writer
  capability**, and **redeploy the last read-only pre-G5 release**. The system returns to read-only + dry-run. No boolean,
  environment variable, CLI option, or generic feature flag may restore writing — write capability exists only while a
  valid, commit-bound contract record is present, and rollback removes it.
- **Risks/failure behavior:** if any safety test regresses or a contract is unconfirmed, the gate stays OFF (fail-closed);
  no live write is possible.
- **Definition of Done:** gate logic tested; canary runbook complete; owner sign-off obtained before the supervised canary.
- **Approval boundary:** **explicit, separate owner approval is required before the supervised canary and before any live
  write.** Stop and wait.
