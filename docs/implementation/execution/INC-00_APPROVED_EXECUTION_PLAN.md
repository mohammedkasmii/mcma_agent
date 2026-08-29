# INC-00 Approved Execution Plan

**Status:** APPROVED FOR IMPLEMENTATION  
**Source commit:** `f3e543c2e02c3a25916721f36c63c401574947a0`  
**Implementation branch:** `phase5/inc-00-baseline-containment`  
**Scope:** INC-00 only  
**INC-01:** NOT AUTHORIZED

This consolidated specification supersedes the earlier INC-00 Execution Plan Rev. 2 and all subsequent amendment
messages. Implement from this file. If another instruction conflicts with this file, stop and ask the owner.

No browser launch, external network or live MCMA access, real session/data/log access, firewall command execution,
commit, push, or work on another increment is authorized.

## 1. Preconditions and protected files

Before editing, run and report:

```text
git branch --show-current
git rev-parse HEAD
git status --short
```

Required branch: `phase5/inc-00-baseline-containment`.

For the first implementation change, HEAD must be
`f3e543c2e02c3a25916721f36c63c401574947a0`. Stop if either value is wrong. Preserve all existing user/untracked
files. Never open or modify:

- `data/`;
- `mcma_auth_state.json` or any other session/cookie/token file;
- `MCMA_REBUILD_MASTER_PROMPT.md`;
- `.claude/settings.local.json`;
- unrelated untracked files.

Use the relevant installed TDD, writing-plans, sharp-edges, insecure-defaults, modern-python, and
spec-to-code-compliance guidance. Do not use unrelated skills merely because they are installed.

## 2. Required outcome

INC-00 permanently removes or hard-refuses every baseline live form-filling entry point before Playwright/browser
construction. No environment value, configuration value, API field, CLI argument, feature flag, boolean, or ordinary
rollback may restore it. INC-00 introduces no replacement writer.

The API binds to `127.0.0.1` only. No tracked launcher advertises or opens LAN access. No tracked script creates the
`profile=any` firewall rule. Manual login/session capture, session keeping, notification extraction, local notification
actions, and the static dashboard remain available as explicitly preserved read/local features.

## 3. Exact refusal contract

Each edited executable module defines its own clearly named constant with this identical literal (do not introduce a
new shared production module before INC-03):

```python
_INC00_CONTAINMENT_MSG = (
    "Baseline live-write capability was permanently removed at INC-00; "
    "the only live-write path is the post-G5 VerifiedMissionWriter."
)
```

Contracts:

- `run_dossier.main` and `trigger.py`: exact `SystemExit` carrying the message.
- `main.process_workflow`, `browser.mode_normal.fill_mode_normal`,
  `browser.mode_conventionne.fill_garage_conventionne`, and
  `browser.mode_conventionne._edit_single_row_dynamic`: exact `RuntimeError` carrying the message.
- `/api/v1/fill-dossier` and `/api/v1/fill-dossier-from-wexia`: absent from `main.app.routes`.

Tests assert the exact type and message. Do not accept tuples of exception types.

## 4. Production and launcher changes

### 4.1 `run_dossier.py`

- Replace the complete `main()` body with `raise SystemExit(_INC00_CONTAINMENT_MSG)`.
- Remove now-unused `argparse`, mapper, `process_workflow`, and any other imports made unused by the replacement.
- Keep harmless parsing/helper functions only if still deliberately retained; none may be reachable from `main()`.
- Update the module description/usage text so it does not advertise working baseline automation.

### 4.2 `main.py`

- Delete the two fill-route functions and decorators.
- Delete `FillDossierRequest` and `WexiaDossierRequest`; keep `NotificationActionUpdate`.
- Replace the complete `process_workflow` body with `raise RuntimeError(_INC00_CONTAINMENT_MSG)`.
- Remove write-only imports made unused: `WexiaToDossierMapper`, `StructuredLogger`, `install_safety_policy`,
  `search_and_open_mission`, `fill_main_form`, `fill_mode_normal`, `fill_mode_conventionne`, and unused configuration
  constants such as `TEST_MODE`, `BASE_URL`, and `TEMP_DIR`.
- Keep `async_playwright`, `AUTH_STATE_FILE`, `LOGS_DIR`, and `fetch_all_notifications` because the preserved
  notification route uses them.
- Change Uvicorn to `host="127.0.0.1"`.
- Delete the entire local-IP discovery block, including `import socket`, `local_ip`, `8.8.8.8`, hostname fallback, and
  the colleague/LAN banner. Startup must print only the localhost URL and must perform no IP-discovery connection.
- Change the FastAPI title/description to describe a temporarily contained local/read-only notifications service, not
  an active dossier-filling agent.

### 4.3 `browser/mode_normal.py`

- Replace the complete `fill_mode_normal` body with the exact `RuntimeError` refusal.
- Remove imports made unused.
- The executable body must contain no checkmark click and no
  `MontantChargeMutuelle`/`MontantChargeSocietaire` write.

### 4.4 `browser/mode_conventionne.py`

- Replace the complete bodies of `fill_garage_conventionne` and `_edit_single_row_dynamic` with the exact
  `RuntimeError` refusal.
- Remove imports made unused by those body replacements, but preserve all imports required by pure helpers.
- Preserve `_match_single_rubrique`, `match_all_rubriques`, `RUBRIQUE_MATCH_ALIASES`, and `GCLogger` for existing tests.
- Keep `fill_mode_conventionne = fill_garage_conventionne`; it must resolve to the refusing function.

### 4.5 `garage_conventionne.py`

- No edit is expected. Test both re-exported writer aliases and the preserved helper exports.

### 4.6 `menu.py`

- Remove the option-1 `run_dossier.py` subprocess invocation.
- Option 1 prints a clear permanent-containment notice.
- Update its displayed text without changing options 2–6.

### 4.7 `trigger.py`

- Replace the entire HTTP smoke script with a refusal-only executable using the exact `SystemExit` contract.
- Remove `requests`, payload construction, and the POST.

### 4.8 Login success text

- In `auth_setup.py`, change only the post-login success guidance that recommends `run_dossier.py`.
- State that session capture succeeded, baseline dossier filling is disabled during the rebuild, and read-only
  notification functionality remains available.
- Do not otherwise modify login, OTP, session creation, or storage behavior.

### 4.9 Windows launchers and shortcut

- `setup_new_pc.bat`: remove the recommendation to run `run_dossier.py`; show login plus read-only notification next
  steps.
- `DEMARRER_MCMA.bat`: describe the local/read-only dashboard, not automation.
- `Lancer_MCMA_Dashboard.bat`: remove route/IP discovery and colleague/LAN URL; keep localhost only.
- `Ouvrir_MCMA_Employe.bat`: remove the `192.168.1.17` URL and replace the body with a clear temporary-disabled notice.
- Delete/retire `MCMA_Dashboard_Employe.url`; do not rewrite it to localhost.

### 4.10 Firewall automation

- `Autoriser_Reseau_Local.bat`: remove the `netsh ... add rule ... profile=any` block. It must not add or open any rule.
  Replace it with a notice pointing to the decommission runbook.
- Add `deploy/decommission_firewall.md` with the exact administrator commands:

```bat
netsh advfirewall firewall delete rule name="MCMA Dashboard (Port 8000)"
netsh advfirewall firewall show rule name="MCMA Dashboard (Port 8000)"
```

The verification expects Windows to report that no rules match. Do not execute either command. Repository containment
and host decommission are separate; do not claim the host rule was removed without owner-executed evidence.

### 4.11 Root `README.md`

- Add a prominent notice that baseline form filling and both fill endpoints are permanently disabled during the rebuild.
- Mark existing `run_dossier.py` and fill-API instructions as disabled/retained only for historical context.
- Do not rewrite `docs/recovery/*`, `docs/architecture/*`, or `docs/implementation/*` except this approved execution-plan
  file, because those documents intentionally record earlier states and approved targets.

## 5. Complete execution-surface rule

Tracked executable/user-facing surfaces covered by INC-00 include:

- `run_dossier.py`;
- `main.process_workflow` and the two fill routes;
- both baseline mode writers and the conventionne compatibility bridge;
- `menu.py` option 1;
- `trigger.py`;
- `setup_new_pc.bat`, `DEMARRER_MCMA.bat`, `Lancer_MCMA_Dashboard.bat`,
  `Ouvrir_MCMA_Employe.bat`, and `MCMA_Dashboard_Employe.url`;
- `Autoriser_Reseau_Local.bat`;
- root `README.md` and the stale post-login instruction in `auth_setup.py`.

In tracked production code, `updateDevisDet` and `createRapportDefDet` are invoked only by the writer bodies being
replaced. Endpoint names may legitimately remain as inert data in a safety blocklist, docstring, recovery document, or
mock contract. Do not treat those inert references as executable call sites.

Untracked `v12_camoufox_output/` residue is outside the repository scope. Do not read or modify it. Tests may assert
that no tracked production module imports `v12_camoufox_output.generated_client`, but must not depend on the untracked
directory existing.

## 6. Tests-first implementation

Add `tests/baseline_containment/` with the following 15 test files. Behavioral tests are written and run RED for the
intended reason before their minimal implementation. Structural-lock tests are regression tests and need not
independently start RED. Preservation tests are characterization tests and may start GREEN; record their before/after
result honestly.

### 6.1 `test_run_dossier.py`

- Pin `sys.argv` to `["run_dossier.py"]`.
- Before the baseline RED invocation, monkeypatch `find_default_json` to return `""` so no input directory is scanned.
- Monkeypatch `load_json_data` and `process_workflow` to fail-if-called sentinels where those attributes exist.
- After implementation, assert exact `SystemExit` message and that `process_workflow` is no longer exposed/imported.
- The baseline must fail for the wrong message/remaining import, not pass because pytest arguments or real input are read.

### 6.2 `test_trigger.py`

- Use `runpy.run_path("trigger.py")`.
- Monkeypatch `requests.post` to a fail-if-called sentinel for the baseline RED run.
- Assert exact `SystemExit` message after implementation and prove no HTTP call occurs.

### 6.3 `test_process_workflow.py`

- Before the baseline RED invocation, monkeypatch `main.TEMP_DIR` to a location under `tmp_path` with `raising=False`.
- Point `main.AUTH_STATE_FILE` to a guaranteed-absent path under `tmp_path`.
- Replace `main.async_playwright` with a fail-if-called sentinel.
- Assert exact `RuntimeError` message after implementation and no Playwright construction.
- The RED run must not create a repository temp directory or inspect a real session path.

### 6.4 `test_api_routes.py`

- Assert both fill paths are absent from `main.app.routes`.
- A secondary TestClient POST must be non-success (`404` or `405` are both valid because `StaticFiles` is mounted at
  `/`). Do not require exactly `404`.
- Prove the old handler cannot execute.

### 6.5 `test_modes.py`

- Use a `MagicMock`/`AsyncMock` page and an explicit fake/in-memory logger for every baseline RED invocation so no
  `StructuredLogger` writes under `logs/`.
- Assert exact `RuntimeError` messages for all three contained writer functions.
- Assert zero page calls/awaits.

### 6.6 `test_garage_bridge.py`

- Assert both re-exported writer aliases raise the exact `RuntimeError` message.
- Assert `match_all_rubriques`, `_match_single_rubrique`, `RUBRIQUE_MATCH_ALIASES`, and `GCLogger` still import.

### 6.7 `test_menu.py`

- Parse the option-1 branch and prove it cannot invoke `run_dossier.py`.
- Assert the disabled notice and preservation of options 2–6.

### 6.8 `test_bind.py`

- Assert `host="127.0.0.1"` and absence of `host="0.0.0.0"`.
- Assert the startup block contains no `8.8.8.8`, `local_ip`, colleague banner, or socket-based IP discovery.

### 6.9 `test_launchers.py`

- Prove the employee BAT no longer contains `192.168.1.17` or opens a URL.
- Prove the `.url` file is absent.
- Prove the dashboard launcher contains no IP discovery or colleague URL.
- Prove new-PC setup no longer recommends `run_dossier.py`.
- Prove the master launcher no longer advertises automation.

### 6.10 `test_firewall.py`

- Inspect tracked BAT files and prove none combines an add-rule command with `profile=any`.
- Assert the decommission runbook exists and contains the exact named-rule delete and verification commands.

### 6.11 `test_readme.py`

- Assert root README clearly says baseline filling and both endpoints are disabled.

### 6.12 `test_ast_no_mutation.py`

- AST-parse `process_workflow`, `fill_mode_normal`, `fill_garage_conventionne`, and `_edit_single_row_dynamic`.
- Each body must be exactly one `Raise`, optionally preceded by a docstring expression.
- No executable page/write call or charge-mutuelle/row-endpoint string may remain in those bodies.

### 6.13 `test_no_restore.py`

- Set representative environment variables (`TEST_MODE=0`, `ENABLE_WRITES=1`, `MCMA_WRITE=1`) and monkeypatch
  `core.config.TEST_MODE=False`.
- Invoke every refusing function with synthetic arguments and explicit fake loggers.
- Assert the exact refusal remains unconditional.

### 6.14 `test_row_write_unreachable.py`

- Use an explicit tracked file set: `main.py`, `run_dossier.py`, `menu.py`, `trigger.py`, `garage_conventionne.py`,
  `browser/mode_normal.py`, `browser/mode_conventionne.py`, `browser/form_filler.py`,
  `browser/mission_navigator.py`, and `browser/safety_interceptor.py`.
- Reuse the AST refusal-body check.
- Distinguish executable call sites from endpoint names in blocklists/docstrings.
- Assert no tracked production import references `v12_camoufox_output.generated_client`; do not inspect that untracked
  directory.

### 6.15 `test_preservation.py`

- `/health` returns `200`.
- Redirect `main.LOGS_DIR` to `tmp_path` before any notification-action/cache request. Seed only synthetic temporary
  JSON. GET notification actions/cache returns `200`; POST notification actions writes only under `tmp_path`.
- Check `/api/v1/notifications` and `/api/v1/auth/launch-login` by route registration only; never invoke them.
- Import `auth_setup`, `session_keeper`, `get_notifications`, and `browser.notifications` with a fail-if-called
  Playwright sentinel and a guard against write-mode filesystem opens during the import window. Assert expected exports
  remain available and no import-time launch/write occurs.
- Assert menu options 2–6 remain present.
- Verify the static dashboard mount remains registered; do not exercise any route that can launch Playwright.

## 7. Safe verification

INC-01's authoritative egress guard does not exist yet. Before running any test, inspect it and confirm that it uses only
AST/source checks, temporary directories, TestClient on non-browser routes, and fail-if-called sentinels. No test may
launch Chromium or contact MCMA/any external host.

Run:

```text
python -m pytest tests/baseline_containment -v
python -m pytest tests/ -v
git diff --check
git status --short
```

Before the complete suite, inspect every existing test and reconfirm the Phase 2 evidence that it cannot reach MCMA.
Do not run a test whose safety cannot be established statically.

## 8. Expected file scope

### Modified — 13 unique files

- `run_dossier.py`
- `main.py`
- `menu.py`
- `trigger.py`
- `auth_setup.py` (success guidance only)
- `browser/mode_normal.py`
- `browser/mode_conventionne.py`
- `Autoriser_Reseau_Local.bat`
- `setup_new_pc.bat`
- `DEMARRER_MCMA.bat`
- `Lancer_MCMA_Dashboard.bat`
- `Ouvrir_MCMA_Employe.bat`
- `README.md`

### Deleted — 1 file

- `MCMA_Dashboard_Employe.url`

### Added

- `docs/implementation/execution/INC-00_APPROVED_EXECUTION_PLAN.md` (this file)
- `deploy/decommission_firewall.md`
- `tests/baseline_containment/` containing exactly the 15 test files in section 6

### Tested only, normally unedited

- `garage_conventionne.py`

### Explicitly preserved

- Functional behavior of `auth_setup.py` apart from its success guidance
- `session_keeper.py`
- `get_notifications.py`
- `browser/notifications.py`
- read/local routes in `main.py`: health, launch-login registration, notifications registration, cached notifications,
  and notification actions
- `static/`
- menu options 2–6
- conventionne pure helpers
- `core/*`
- `docs/recovery/*`, `docs/architecture/*`, and existing `docs/implementation/*`
- dependencies/configuration, `data/`, and session/user files

If a necessary change falls outside this list, stop and report it before editing that file.

## 9. Commit, rollback, and stop rules

- Keep all implementation changes uncommitted. Do not commit or push.
- Do not execute firewall commands.
- Never revert INC-00 to restore the baseline writer. Fix forward within the contained state.
- `0290fe9` is historical evidence, never an operational rollback target.
- Do not start INC-01, add its egress guard, extend the mock server, or implement replacement architecture.

## 10. Definition of Done and final report

Done requires:

- all behavioral containment tests green after documented RED evidence;
- all structural-lock and preservation tests green;
- complete safe offline suite green;
- exact refusal types/messages;
- no baseline reachable call path to the contained writer functions or row endpoints;
- no browser construction before refusal;
- loopback-only bind and no IP-discovery network action;
- no tracked LAN launcher/shortcut or firewall-creation automation;
- truthful README/login/launcher guidance;
- preserved read/local features verified using only synthetic temporary data;
- no dependency/config/database/session/user-file changes;
- no commit or push.

Report:

1. branch, starting SHA, and final status;
2. RED then GREEN evidence for every behavioral test;
3. characterization before/after results;
4. exact changed/deleted/added files;
5. `git diff --check` result;
6. containment and full-suite results;
7. confirmation that no browser, external connection, firewall command, real log/data/session access, commit, push, or
   INC-01 work occurred.

Then STOP for owner review.
