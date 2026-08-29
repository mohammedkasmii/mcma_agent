# Phase 0 — Baseline containment & test safety

These increments must land **first**, before any other work. They protect against (a) the **baseline's own** dangerous
live-write paths running during the multi-phase rebuild, (b) a test reaching the live portal, and (c) refactors silently
changing working behavior.

---

## INC-00 — Baseline live-write **permanent** containment (reviews SEC-1, SEC-6; correction #1)

- **Purpose/outcome:** **Permanently and unconditionally remove the baseline's live-write capability and LAN exposure on
  this branch** — not gate it behind a runtime flag. The baseline is known-unsafe (INV-1/2/3/8 VIOLATED). After INC-00 the
  legacy writer **cannot issue a row write at all**, and cannot be restored through configuration, environment variables,
  CLI arguments, or feature flags. The **only** path to a live write, ever, is the new `VerifiedMissionWriter` after **G5**.
- **Why here:** first control; leaving the baseline writer/API live (or flag-restorable) for the whole rebuild is the largest standing risk.
- **Prerequisites:** none
- **Prerequisite rationale:** the first increment.
- **Addresses:** standing prohibition applied to the baseline; INV-1/2/3/8, INV-11 (interim); F6, F8, F18.
- **Containment mechanism (no runtime boolean — correction #1):** the write-performing code paths are **deleted or
  hard-`raise`d** (their bodies replaced by an unconditional `RuntimeError("baseline live-write permanently removed; use
  the post-G5 VerifiedMissionWriter path")`), the fill-dossier routes are removed, the API bind is changed to loopback in
  code, and the firewall rule is removed. There is **no** `MIGRATION_MODE` and no other switch. The baseline's read-only
  surfaces (notification extraction, dashboard) may keep running until INC-22.
- **Baseline execution-surface inventory that MUST be contained (at minimum):**
  1. `run_dossier.py` (CLI form-fill entrypoint) — refuses at startup.
  2. `menu.py` option 1 (and any launcher `.bat`/`.url` that invokes it, e.g. `DEMARRER_MCMA.bat`, `Ouvrir_MCMA_Employe.*`) — the fill action is removed.
  3. `main.py` `process_workflow` and **every** form-filling API route (`POST /api/v1/fill-dossier`, `POST /api/v1/fill-dossier-from-wexia`) — routes removed.
  4. Direct Mode Normal / Mode Conventionné mutation paths (`browser/mode_normal.py` `fill_mode_normal`, `browser/mode_conventionne.py` `fill_garage_conventionne`/`_edit_single_row_dynamic`) — write functions hard-`raise`.
  5. Row-mutation callers (anything invoking `updateDevisDet` / `createRapportDefDet`, the col-7 checkmark clicks) — removed.
  6. Forced charge-mutuelle writes (`browser/mode_normal.py:122-144`) — removed.
  7. Non-loopback API binding (`main.py:287` `host="0.0.0.0"`) — changed to `127.0.0.1` in code.
  8. `Autoriser_Reseau_Local.bat` `profile=any` firewall rule — removed now (`deploy/decommission_firewall.md`).
- **Target modules/files introduced:** `tests/baseline_containment/`, `deploy/decommission_firewall.md`. No config flag.
- **DB migration impact:** none.
- **Dependency/config impact:** none (no new flag).
- **Feature flags/adapters:** **none by design** — containment is unconditional so it cannot be a footgun.
- **Out-of-scope:** the new stack (later increments). INC-00 only *removes* baseline write capability.
- **Tests-first (each proves refusal BEFORE any Playwright launch, and that no baseline controller can issue a row write):**
  - **`test_run_dossier_refuses_at_startup_before_browser_launch`**.
  - **`test_menu_option1_fill_action_removed`**.
  - **`test_process_workflow_hard_raises`** and **`test_fill_dossier_routes_absent`** (both API routes 404/removed).
  - **`test_mode_normal_fill_hard_raises_before_playwright`** and **`test_mode_conventionne_fill_hard_raises_before_playwright`**.
  - **`test_no_baseline_controller_can_issue_row_write`** (static/behavioral: no reachable path posts `updateDevisDet`/`createRapportDefDet`).
  - **`test_forced_charge_mutuelle_write_removed`**.
  - **`test_api_binds_loopback_in_code`** (no `0.0.0.0` bind reachable).
  - **`test_no_env_config_or_cli_can_re_enable_baseline_write`** (setting any env/arg/flag does not restore a writer).
- **Initial failing-test expectation:** fail (baseline still writes / binds 0.0.0.0 / routes present).
- **Mock/fixtures:** none (refusals occur before any browser launch).
- **Implementation steps:** remove fill-dossier routes → hard-`raise` the Mode Normal/Conventionné write functions and the
  charge-mutuelle path → make `run_dossier`/`menu` fill refuse at startup → change API bind to loopback → remove the
  firewall rule → prove no reachable row-write path remains.
- **Acceptance criteria:** no baseline live write is possible by any means (no flag restores it); the baseline API is not LAN-exposed; the firewall rule is gone.
- **Safe offline verification:** `python -m pytest tests/baseline_containment -v`.
- **Safety gates:** a **standing prohibition** enforced from day one and part of every gate G0–G5.
- **Expected git-diff scope:** removals/hard-raises in the baseline write paths listed above + `main.py` bind + `deploy/` +
  tests. This is the **sole** pre-INC-22 baseline production edit and it **only removes capability**.
- **Rollback:** rollback returns to the **last safe read-only / contained version** and **never restores the unsafe
  writer**. There is no configuration that re-enables baseline writes. (See `ROLLBACK_PLAN.md` INC-00 row.)
- **Risks/failure behavior:** fail-closed and unconditional; nothing to misconfigure.
- **Definition of Done:** containment tests green; baseline write capability permanently removed; LAN exposure gone.
- **Approval boundary:** stop before INC-01.

> **Note:** INC-00 is the sole exception to "no baseline production edits before INC-22" — it *permanently removes*
> capability (contains the baseline unconditionally), never adds it, and is the safest possible first step.

---

## INC-01 — Test egress lockdown

- **Purpose/outcome:** No test process — including subprocesses and Chromium — can reach the production host. This is the
  precondition for every later increment that touches the browser.
- **Why here:** ADR-0010 step 1; the master prompt requires unconditional production-egress blocking before browser work.
- **Prerequisites:** INC-00
- **Prerequisite rationale:** baseline write capability removed first.
- **Addresses:** TEST_STRATEGY §1; the recovery "no production-domain blocking exists" gap (`TEST_EVIDENCE.md`); INV-10.
- **Baseline files modified/retired:** none retired. Adds test-infra only.
- **Target modules/files introduced:** `conftest.py` (repo root), `tests/_egress_guard.py` (socket guard + pytest plugin
  hook), `pyproject.toml` (registers the plugin + `pytest-socket` config under `[tool.pytest.ini_options]` — **pytest
  config lives in `pyproject.toml` only**), `ci/no-egress.md` (OS/CI runbook),
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
- **Prerequisites:** INC-01
- **Prerequisite rationale:** characterization of any browser path must be offline (egress lockdown first).
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
