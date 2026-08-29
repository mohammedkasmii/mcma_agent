# SYSTEM OVERVIEW

**Baseline commit SHA:** `0290fe9df24c9e2f2b054ee4f8b14b8267f07b12`
Facts are cited to `file:line`. Statements marked *(inference)* are reasoned conclusions, not direct evidence.

---

## 1. Purpose

MCMA SinAuto automation agent: a Playwright-driven tool that logs a human expert into the MAMDA/MCMA "SinAuto" insurance portal, extracts notification/alert queues for an office dashboard, and (for form-filling) navigates to an expertise mission and fills repair-estimate rubrique rows. Final, irreversible portal actions are intended to remain a human responsibility.

- Base URL: `https://sinauto.mamda-mcma.ma/SinAuto_MCMA/` (`core/config.py:22`).
- Mission/dashboard route: `.../expertise/FrontExpert/` (`core/config.py:23`).

## 2. Components and responsibilities (verified)

| Layer | Module(s) | Responsibility |
|---|---|---|
| Config | `core/config.py` | URLs, relative paths, timeouts, `TEST_MODE=True` master switch (:19) |
| Domain constants | `core/constants.py` | Rubrique catalog (:13-42), origin aliases (:47-49), family→rubrique matrix (:54-67), match aliases (:72-183), TVA/CENT decimals (:186-187) |
| Utilities | `core/utils.py` | Text/registration normalizers, search-key extraction (`extract_search_matricule` :59-70) |
| Logging | `core/logger.py` | `StructuredLogger` → one JSON file per run (:23-78); `capture_screenshot` (:81-92) |
| Auth | `auth_setup.py`, `session_keeper.py` | Manual login + storage-state save; keep-alive/health daemon |
| Mapping | `mapper/wexia_mapper.py`, `mapper.py` (shim) | Wexia payload → deterministic MCMA dossier payload with Decimal money |
| Browser I/O | `browser/mission_navigator.py`, `browser/form_filler.py`, `browser/mode_normal.py`, `browser/mode_conventionne.py`, `browser/dom_helpers.py`, `browser/notifications.py`, `browser/safety_interceptor.py` | Search/open mission, fill header, fill rubrique rows (two modes), notification extraction, network interception |
| Orchestration | `main.py` (`process_workflow`), `run_dossier.py` | Wire mapping + browser steps; CLI and HTTP entry |
| Web/API | `main.py` (FastAPI), `static/` | REST endpoints + employee dashboard |
| Notifications CLI | `get_notifications.py` | Populate notification cache JSON offline of the API |
| Employee launchers | 7 `.bat` + `MCMA_Dashboard_Employe.url` | 1-click login/dashboard/notifications/firewall on Windows |
| Offline replica | `mock_server.py` | Standalone FastAPI mock of the portal page (127.0.0.1:8080); **orphaned — no test uses it** |

## 3. Primary data flows (verified)

1. **Auth →** human logs into headed Chromium (`auth_setup.py`) → `mcma_auth_state.json` (Playwright storage state, single file, plaintext).
2. **Notifications →** saved state → Chromium → in-page AJAX `getAlerte` with `length=-1` (`browser/notifications.py:33-101`) → `logs/mcma_notifications.json` → dashboard reads cache (`main.py:119-129`).
3. **Fill dossier →** dossier JSON → `WexiaToDossierMapper` (`mapper/wexia_mapper.py`) → `process_workflow` (`main.py:178-256`) → `search_and_open_mission` → `fill_main_form` → `fill_mode_normal` | `fill_garage_conventionne` → **row-level writes** → `page.pause()` human review (`main.py:244`).
4. **Employee tracking →** dashboard status/notes → `POST /api/v1/notification-actions` → `logs/notification_actions.json` + browser `localStorage`.

## 4. Entry points (verified)

- `python auth_setup.py` — one-time login/session save.
- `python main.py` — FastAPI + dashboard, binds `0.0.0.0:8000` (`main.py:287`).
- `python run_dossier.py [--json ...]` — CLI form-fill.
- `python get_notifications.py [--headless]` — notification cache populator.
- `python session_keeper.py [--check|--interval N|--auth-file P]` — keep-alive/health.
- `python menu.py` — interactive text menu.

## 5. External dependencies & boundaries (verified)

- **Live portal** `sinauto.mamda-mcma.ma` — reached by auth, notifications, session-keeper and form-fill paths.
- **Office LAN** — the API binds all interfaces; two employee artifacts hardcode `192.168.1.17:8000` (`Ouvrir_MCMA_Employe.bat:4`, `MCMA_Dashboard_Employe.url:2`) while `Lancer_MCMA_Dashboard.bat:23-27` auto-detects the IP *(inference: guaranteed drift on DHCP lease change)*.
- **Google Fonts CDN** — `static/index.html:8-10` and `mock_server.py` CDN assets require internet *(inference: degrades on an air-gapped LAN)*.
- **Filesystem as datastore** — `logs/` holds both logs and the application's only persistent state (notification cache, employee actions). No SQLite/DB on this branch.

## 6. What is explicitly NOT present on this branch (verified)

SQLite/WAL persistence, Server-Sent Events, a Vite/React frontend, a multi-account vault, per-account locks, encrypted auth state, and distinct PLAN/PREVIEW/DRAFT/FINAL execution modes are **described in `PROJECT_ARCHITECTURE_BLUEPRINT.md` but not implemented here**. Treat the blueprint as a target, not a description of this baseline. (Architecture design is out of scope for this phase.)
