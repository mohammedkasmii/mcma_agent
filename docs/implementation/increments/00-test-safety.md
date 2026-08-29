# Phase 0 — Baseline containment & test safety

These increments must land **first**, before any other work. They protect against (a) the **baseline's own** dangerous
live-write paths running during the multi-phase rebuild, (b) a test reaching the live portal, and (c) refactors silently
changing working behavior.

---

## INC-00 — Baseline live-write containment (review SEC-1, SEC-6)

- **Purpose/outcome:** **Neutralize the baseline's live-write and unauthenticated-exposure surfaces before anything else**,
  so the "no live form filling until G5" prohibition binds the *baseline* too — not only the new stack. The baseline is
  known-unsafe (INV-1/INV-2/INV-3/INV-8 VIOLATED: preview writes rows, wrong-mission writes, fail-open interceptor, forced
  charge-mutuelle) and, being additive, keeps running until INC-22 unless contained now.
- **Why here:** it is the very first control; leaving the baseline writer/API live for the whole rebuild is itself the
  largest standing risk (safety review Finding 1/6).
- **Prerequisites:** none (first increment).
- **Addresses:** the standing prohibition (README Global constraints; RELEASE_GATES) applied to the baseline; INV-1/2/3/8,
  INV-11 (interim); F6, F8, F18.
- **Baseline files modified/retired:** **structurally disable** the baseline live-write entrypoints and LAN exposure for
  the duration of the rebuild — the `fill-dossier` / `fill-dossier-from-wexia` routes and `process_workflow` in `main.py`
  are guarded to refuse to run (return a hard "disabled during migration" error), the Mode-Normal forced charge-mutuelle
  path is made unreachable, the legacy API is **bound to loopback in code** (not `0.0.0.0`), and the
  `Autoriser_Reseau_Local.bat` `profile=any` firewall rule is **removed now** (not deferred to INC-18/22).
- **Target modules/files introduced:** a small `MIGRATION_MODE` guard in `core.config` (default ON during the rebuild)
  read by the baseline entrypoints; `deploy/decommission_firewall.md`. Tests under `tests/baseline_containment/`.
- **DB migration impact:** none.
- **Dependency/config impact:** one config flag `MIGRATION_MODE` (ON by default until INC-22 cutover completes).
- **Feature flags/adapters:** `MIGRATION_MODE` — while ON, the baseline cannot perform a live write or bind non-loopback.
- **Out-of-scope:** the new stack (later increments). This increment only *contains* the baseline.
- **Tests-first:**
  - **`test_baseline_fill_dossier_refuses_while_migration_mode`** (the write entrypoints hard-fail).
  - **`test_baseline_process_workflow_refuses_while_migration_mode`**.
  - `test_baseline_api_binds_loopback_only_while_migration_mode`.
  - `test_forced_charge_mutuelle_path_unreachable_while_migration_mode`.
- **Initial failing-test expectation:** fail (the guard does not exist; baseline still writes / binds 0.0.0.0).
- **Mock/fixtures:** none (guards are checked before any browser launch).
- **Implementation steps:** add `MIGRATION_MODE` → guard the write entrypoints (fail-closed) → force loopback bind →
  remove the all-profiles firewall rule → document decommission.
- **Acceptance criteria:** with `MIGRATION_MODE` ON, no baseline live write is possible and the baseline API is not
  LAN-exposed; the firewall rule is removed.
- **Safe offline verification:** `python -m pytest tests/baseline_containment -v`.
- **Safety gates:** a **standing prohibition** — the baseline may not perform a live write for the entire rebuild; this is
  part of every gate G0–G5.
- **Expected git-diff scope:** small guards in `main.py`/`core/config.py`/baseline write path (the **only** baseline
  production edits before INC-22, and they are *containment* edits that remove capability, never add it), `deploy/`, tests.
- **Rollback:** `MIGRATION_MODE` OFF restores baseline behavior — but this is **not** done until INC-22 cutover, and never
  to re-expose the unauth API. Firewall re-add is a deliberate operational step.
- **Risks/failure behavior:** fail-closed — if the guard cannot be read, the baseline entrypoints refuse to run.
- **Definition of Done:** containment tests green; baseline write + LAN exposure neutralized for the rebuild.
- **Approval boundary:** stop before INC-01.

> **Note:** INC-00 is the sole exception to "no baseline production edits before INC-22" — it *removes* capability
> (contains the baseline), never adds it, and is the safest possible first step. It is called out in README and RELEASE_GATES.

---

## INC-01 — Test egress lockdown

- **Purpose/outcome:** No test process — including subprocesses and Chromium — can reach the production host. This is the
  precondition for every later increment that touches the browser.
- **Why here:** ADR-0010 step 1; the master prompt requires unconditional production-egress blocking before browser work.
- **Prerequisites:** none (first increment).
- **Addresses:** TEST_STRATEGY §1; the recovery "no production-domain blocking exists" gap (`TEST_EVIDENCE.md`); INV-10.
- **Baseline files modified/retired:** none retired. Adds test-infra only.
- **Target modules/files introduced:** `conftest.py` (repo root), `tests/_egress_guard.py` (socket guard + pytest plugin
  hook), `pyproject.toml`/`pytest.ini` (register the plugin + `pytest-socket` config), `ci/no-egress.md` (OS/CI runbook),
  `tests/safety/test_egress_proof.py`.
- **DB migration impact:** none.
- **Dependency/config impact:** add dev-only `pytest-socket`. No runtime dependency change.
- **Feature flags / adapters:** none (always on in tests).
- **Out-of-scope:** any portal/browser logic; the mock server (INC-06).
- **Tests-first (write these first, watch them fail):**
  - **`test_egress_preflight_confirms_os_denial_without_emitting`** (review SEC-2) — a **no-emission** preflight positively
    verifies OS/CI egress denial is in effect (e.g., by inspecting the enforced firewall/namespace policy, not by dialing);
    if it cannot confirm denial, the whole suite **fails closed** and no production-host-dialing test is allowed to run.
  - `test_socket_to_sentinel_host_is_blocked` — the guard blocks a connect to a **dedicated blackhole/sentinel host** used
    as the "production-like" target; the real portal FQDN is **not** dialed by the suite.
  - `test_non_loopback_socket_blocked_by_default` — any non-loopback connect is blocked; loopback to the mock port allowed.
  - `test_subprocess_cannot_reach_sentinel_host` — a spawned `python -c` subprocess attempting the connect is blocked
    (proves the OS/CI layer, not just in-process), and only runs after the no-emission preflight confirms denial.
  - `test_headless_chromium_cannot_reach_sentinel_host` — launching Playwright Chromium and navigating to the sentinel host
    is blocked; gated behind the same preflight.
- **Initial failing-test expectation:** all fail (guard/plugin/preflight not yet present; subprocess/browser reach the sentinel).
- **Mock/fixtures:** a loopback echo/mock stub for the "allowed loopback" assertion; no portal.
- **Implementation steps (safe order):**
  1. Add the in-process socket guard (block all non-loopback; explicit allow for the mock loopback port) as a pytest
     plugin loaded via entry point so it installs **before collection** (not only a fixture).
  2. Add `pytest-socket` with `--disable-socket --allow-hosts=127.0.0.1` as defense-in-depth.
  3. Document the **authoritative** OS/CI egress denial (firewall/network-namespace/no-egress container) covering Python,
     Chromium and subprocesses; make CI enforce it.
  4. Add the subprocess + Chromium proof test.
- **Acceptance criteria:** all four tests pass; CI job runs with OS-level egress denied; `PYTHONSTARTUP`/`sitecustomize`
  are explicitly **not** relied upon (defense-in-depth only, per correction #7).
- **Safe offline verification:** `python -m pytest tests/safety/test_egress_proof.py -v`; CI dry-run with egress disabled.
- **Safety gates blocking progression:** **G0** — no browser-related increment (INC-06+) merges until this passes.
- **Expected git-diff scope:** `conftest.py`, `tests/_egress_guard.py`, `tests/safety/test_egress_proof.py`, test config,
  `ci/`. No `src/` production code.
- **Rollback:** remove the plugin registration + test files; egress lockdown is additive and safely revertible.
- **Risks/failure behavior:** if the OS/CI layer is skipped, the in-process guard alone is insufficient — the runbook and
  CI check are the real control; failure is fail-closed (tests error rather than reach the network).
- **Definition of Done:** four tests green; CI enforces OS egress denial; runbook committed; no production code touched.
- **Approval boundary:** stop; obtain approval before INC-02.

---

## INC-02 — Characterization tests for working baseline behavior

- **Purpose/outcome:** Pin the *current* observable behavior of the genuinely-working baseline paths so later refactors
  are provably behavior-preserving (or intentionally, explicitly changed).
- **Why here:** ADR-0010 step 2; you cannot safely refactor the mapper/notifier without a regression net.
- **Prerequisites:** INC-01 (egress lockdown) — characterization of any browser path must be offline.
- **Addresses:** "preserve every working feature" (master prompt); `FEATURE_INVENTORY.md`; the existing 19 tests
  (`TEST_EVIDENCE.md`) are preserved and extended.
- **Baseline files modified/retired:** none (tests are added around existing code; no production edit).
- **Target modules/files introduced:** `tests/characterization/test_mapper_golden.py`,
  `tests/characterization/test_garage_matcher_golden.py`, `tests/characterization/test_notifications_shape.py`
  (shape/parse only, against saved sanitized HTML/JSON fixtures — never live).
- **DB migration impact:** none.
- **Dependency/config impact:** none.
- **Feature flags/adapters:** none.
- **Out-of-scope:** changing any mapper/notifier behavior; the corrected rules land in INC-04/05, which will
  **intentionally** update these goldens with a documented diff.
- **Tests-first:** golden tests capturing current `WexiaToDossierMapper` outputs for representative inputs (incl. the
  `se00009` fallback), current garage matcher results, and the current notification row-parse shape from saved fixtures.
- **Initial failing-test expectation:** goldens fail until the golden files are generated from the current baseline and
  asserted (then pass on baseline; they become the regression tripwire).
- **Mock/fixtures:** sanitized saved HTML/JSON (no PII, no session) checked into `tests/fixtures/`.
- **Implementation steps:** capture current outputs → freeze as goldens → assert equality → mark which goldens are
  expected to change in INC-04/05 (with a pointer), so a later intentional change updates them deliberately.
- **Acceptance criteria:** goldens green on baseline; a note lists which goldens INC-04/05 will intentionally revise
  (three-origin, glass 19–24, labour, negative-TVA) so the change is never silent.
- **Safe offline verification:** `python -m pytest tests/characterization -v`.
- **Safety gates:** none new; contributes to G1 regression safety.
- **Expected git-diff scope:** `tests/characterization/`, `tests/fixtures/`. No production code.
- **Rollback:** delete the characterization tests/fixtures.
- **Risks/failure behavior:** a golden that encodes a *known defect* (e.g., glass→1) must be labeled as "captures current
  defective behavior; INC-04 corrects it" so no one mistakes it for desired behavior.
- **Definition of Done:** goldens green; defect-capturing goldens labeled; intentional-change list recorded.
- **Approval boundary:** stop; obtain approval before INC-03.
