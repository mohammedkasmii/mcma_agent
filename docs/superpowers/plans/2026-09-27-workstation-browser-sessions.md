# Phase 1B-B — secure local MCMA browser sessions on Windows workstation runners

Branch: `codex/workstation-browser-sessions` (base `1b0423e`). No commits/pushes.

## Scope recap
Add local, per-workstation, DPAPI-encrypted Playwright storage-state sessions for the
two workstation MCMA accounts (`acct-mcma-oujda`, `acct-mcma-nador`), truthful
heartbeat reporting of their readiness, and a minimal GUI for manual login — with
no job dispatch, no form filling, no MAMDA workstation login, no writer changes.

## New modules

| Module | Layer | Playwright? | Purpose |
|---|---|---|---|
| `mcma/portal/workstation_sessions.py` | `mcma.portal` | yes (lazy, inside functions, same pattern as `mcma.portal.browser`) | Narrow adapter: `perform_manual_login()`, `verify_saved_session()`. Reuses `LoginCapability`/`open_login_session`/`ReadCapability.observe_session_state`/`sinauto_contracts`/`open_guarded_context*`. Never returns a page/context/browser. Sync wrappers (`asyncio.run`) so the threaded runner never needs an event loop. |
| `mcma/app/workstation_runner/session_store.py` | `mcma.app` (lightweight, portal-free) | no | DPAPI CURRENT_USER envelope per account at `%LOCALAPPDATA%\MCMA Runner\sessions\<account_id>.bin`. Reuses `mcma.core.dpapi` + `identity.DpapiCurrentUserBackend`. Shape/size validated before encrypt and after decrypt. Atomic same-dir replace, same pattern as `identity.py`. |
| `mcma/app/workstation_runner/sessions.py` | `mcma.app` (lightweight, portal-free) | no | Pure, thread-safe `WorkstationSessionManager` (per-account state: NOT_CONFIGURED / PENDING_VERIFICATION(local only) / LOGIN_REQUIRED / READY / ERROR), `ProbeOutcome` enum, and a `VerificationScheduler` (~5 min, injectable clock) driven off the existing heartbeat cadence — no new timer thread. |
| `mcma/app/workstation_runner/browser_worker.py` | `mcma.app` (lightweight, portal-free) | no (`operations` injected) | One serialized worker thread (mirrors `HeartbeatWorker`'s "one thread, one loop" shape) processing LOGIN/VERIFY commands against an injected `operations` object. Owns cooperative cancellation (`threading.Event`) for the in-flight login. |

## Modified modules
- `heartbeat.py`: `HeartbeatLifecycle` takes `sessions_provider: Callable[[], tuple] = lambda: ()` (recomputed every iteration, never a snapshot) and `on_allowed_accounts: Callable[[tuple], None]`. New `RegistryAccountNotAllowed` (subclass of `RegistryProtocolError`) handling: exactly one immediate empty-session retry, then normal error handling — no unbounded loop, response body never logged.
- `http_client.py`: adds `RegistryAccountNotAllowed`, detected from the fixed `"error"` field of a 400 body (never logs the body).
- `controller.py`: owns a `WorkstationSessionManager` + `BrowserSessionWorker` (both injected as factories, like `client_factory`/`lifecycle_factory`); reconciles `allowed_account_ids` on every heartbeat; on `UNAUTHORIZED` also clears all portal sessions and cancels browser activity; `shutdown()` also (bounded) joins the browser worker before the mutex may be released in `app.py`.
- `gui.py`: renders one row per currently-authorized account (French label, French state, "Se connecter"/"Reconnecter") from a second bounded queue, Tk-thread only; buttons call `controller.request_login(account_id)`.
- `app.py`: composition root wires the real `mcma.portal.workstation_sessions` functions, `session_store.WorkstationSessionStore`, `sessions.WorkstationSessionManager`, `browser_worker.BrowserSessionWorker` — the only lightweight-layer place allowed to import `mcma.portal`.
- `tests/app/workstation_runner/test_import_isolation.py`: the strict check gains the two new portal-free modules; the "full" check (gui+app) is updated to allow `mcma.portal` (the composition root's documented, reviewed dependency) while proving the real `playwright` package is still never imported eagerly.

## State-transition rules (enforced in `sessions.py`, tested in isolation)
- No saved session file → `NOT_CONFIGURED`.
- Saved session file, not yet verified → local `PENDING_VERIFICATION` (GUI: "Vérification…"; wire: omitted from `sessions`, i.e. reads as `NOT_CONFIGURED` server-side) — never `READY` before a positive probe.
- Probe `AUTHENTICATED` → `READY`.
- Probe `LOGGED_OUT` → session file cleared, → `LOGIN_REQUIRED`.
- Probe `INDETERMINATE` or raised failure → `ERROR`, session file untouched.
- Successful manual login: `session_store.save()` must succeed *before* `READY` is set; a cancelled/failed login never touches the previous file.

## Heartbeat/reconciliation
1. First heartbeat after `controller.start()` always sends `sessions: []` (the manager starts with an empty tracked-account set; nothing is known until the server confirms it).
2. Every heartbeat response's `allowed_account_ids` reconciles the tracked set: newly-allowed accounts are seeded (`NOT_CONFIGURED` or `PENDING_VERIFICATION` + an immediate VERIFY command); removed accounts are dropped, their in-flight login (if any) cancelled, and their local session file cleared.
3. `ACCOUNT_NOT_ALLOWED` on a heartbeat → exactly one immediate retry with `sessions: []`, then resumes normal reporting with the freshly-returned `allowed_account_ids`; no response body is logged; no unbounded retry.
4. `UNAUTHORIZED` (revocation) → identity cleared (unchanged from 1B-A) **plus** all portal sessions cleared and browser activity cancelled.
5. Periodic re-verification (~5 min) is driven off the existing `CONNECTED` lifecycle tick using an injectable clock (`VerificationScheduler`), not a new timer thread — testable without real waiting.

## Safety boundaries preserved
- Only `mcma.portal` imports playwright (unchanged contract; `allow_indirect_imports=true` already lets `mcma.app` call into it — no `pyproject.toml` change needed, verified with `lint-imports` after implementation).
- No `LeaseHandle`/`ReadCapability.open_reader` reuse for the probe: `workstation_sessions.py` builds its own guarded, read-only context directly (`open_guarded_context` + a bare `ReadCapability` instance), per the task's explicit instruction.
- No write contracts, no MAMDA account ever reachable from this path (`WORKSTATION_ACCOUNT_IDS` fixed to the two MCMA accounts only, entity hardcoded `"MCMA"`).
- No credential/OTP ever crosses into the GUI, controller, or heartbeat body.
- INC-00 baseline writer untouched; no live-write route added.

## Test plan (new/updated files)
- `tests/app/workstation_runner/test_session_store.py` — round trip, wrong account, corruption/version, oversized/malformed shape, replace-failure preserves previous + no leftover temp file, clear/clear-all, leakage (marker absent from ciphertext/exceptions/repr).
- `tests/app/workstation_runner/test_sessions.py` — every state transition in the table above, isolation between the two accounts, scheduler interval logic with a fake clock.
- `tests/app/workstation_runner/test_browser_worker.py` — single in-flight login, cancellation joins cleanly, VERIFY/LOGIN command handling with a fake `operations`.
- `tests/portal/test_workstation_sessions.py` — fake-Playwright-object unit tests for validation/exception mapping, plus a small `egress_proof`/`requires_egress_isolation` real-Chromium/loopback-portal pair (same convention as `tests/portal/capabilities/test_live_chromium_proof.py`) for manual-login success/cancel and verify AUTHENTICATED/LOGGED_OUT/INDETERMINATE.
- Updated `test_heartbeat.py`, `test_http_client.py`, `test_controller.py`, `test_gui_wiring.py`, `test_import_isolation.py`.

## Verification commands (run and reported individually)
`pytest tests/app/workstation_runner -q`, the runner/registry combined suite, `pytest tests/portal -q`,
`pytest tests/contracts/test_import_boundaries.py -q`, `lint-imports`, `git diff --check`, then the
combined runner/registry suite five times in fresh processes.

Baseline (pre-change, recorded before touching any file):
- `tests/app/workstation_runner -q`: 184 passed
- combined registry suite: 112 passed
- `tests/contracts/test_import_boundaries.py -q`: 4 passed
- `lint-imports`: 7 kept, 0 broken
- `tests/portal -q`: **8 failed, 453 passed, 2 skipped, 35 errors** — pre-existing on this Windows box
  (golden-driver-parity content drift + every `*_live_chromium_proof.py` test failing at setup because
  `requires_egress_isolation`'s structural preflight is Linux-namespace-only). Not caused by this change;
  tracked as a pre-existing condition, not a regression budget.
