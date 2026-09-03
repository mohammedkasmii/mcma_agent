# MCMA Agent

## Purpose & stack
Browser-automation + API agent for the MCMA/MAMDA SinAuto insurance portal (claims/dossier processing).
- Backend: Python >=3.14, FastAPI, Playwright, pydantic, SQLite — managed with `uv` (`pyproject.toml` + `uv.lock`).
- Frontend: React 19 + TypeScript, Vite, TanStack Query, React Router (`frontend/`).

## Architecture & boundaries
- `mcma/` is the current layered rebuild and the source of truth going forward. Enforced one-way layering (`pyproject.toml` `[tool.importlinter]`):
  `mcma.app` → `mcma.execution | mcma.notifications` → `mcma.persistence | mcma.portal` → `mcma.mapping | mcma.planning` → `mcma.domain` → `mcma.core`.
- Single-owner import rules (direct imports only; calling the owning module's API is fine):
  - only `mcma.portal` may `import playwright`
  - only `mcma.persistence` may `import sqlite3`
  - only `mcma.app` may `import fastapi`
- `mcma.core`, `mcma.domain`, `mcma.mapping`, `mcma.planning` are pure — no `playwright`/`sqlite3`/`fastapi`/`httpx`/`requests`.
- `mcma.persistence`/`mcma.portal` may import only `domain` and `core` (not `mapping`/`planning`).
- `mcma` must never import legacy baseline modules: `core`, `browser`, `mapper`, `main`, `mock_server`, `run_dossier`, `menu`, `trigger`, `auth_setup`, `session_keeper`, `get_notifications`, `garage_conventionne`, `testsupport`, `api`, `portal`, `workflows`, `tools`.
- Repo-root legacy files (`core/`, `browser/`, `main.py`, `mapper.py`, `mock_server.py`, `run_dossier.py`, …) are the frozen baseline, kept temporarily until INC-22 retirement — do not extend them; new work goes in `mcma/`.
- `frontend/` is a separate app: `src/app`, `src/features`, `src/shared`.

## Commands
Backend (repo root):
- Install: `uv sync`
- Tests: `python -m pytest` (runs under an egress lockdown; deselect OS-level egress tests locally with `-m "not egress_proof"`)
- Import boundaries: `lint-imports`

Frontend (`frontend/`):
- Dev server: `npm run dev`
- Build: `npm run build`
- Unit tests: `npm run test:run` (watch mode: `npm run test`)
- Typecheck: `npm run typecheck`
- E2E: `npm run e2e`

## Safety constraints
- **INC-00: baseline live form-filling is permanently disabled.** `run_dossier.py` refuses at startup and never launches a browser; the `/api/v1/fill-dossier` and `/api/v1/fill-dossier-from-wexia` routes are removed; no env var, config value, CLI argument, or feature flag restores it. The only sanctioned future live-write path is the post-G5 `VerifiedMissionWriter`. Never restore or work around the baseline writer.
- Tests run under an egress lockdown (`pytest-socket` + a custom `testsupport.egress_guard` layer, wired via `pyproject.toml` `[tool.pytest.ini_options]`): only loopback (`127.0.0.1`, `::1`) network access is permitted. Never add `--no-sandbox` or otherwise bypass this. Never modify the host firewall.
- Respect the import-linter contracts above; a change that violates them should be redesigned, not exempted.

## Workflow
- Delivery is increment-based; `docs/implementation/` (execution plans, release gates, rollback plan, traceability backlog) is the authoritative process record — check it before large or safety-relevant changes.
- Work tests-first. `tests/baseline_containment/` (INC-00 refusal contracts) and the import-linter contracts must stay green.

## Definition of completion
- `python -m pytest` and `lint-imports` pass for backend changes.
- `npm run typecheck` and `npm run test:run` pass for frontend changes.
- No import-boundary or INC-00 safety rule listed above is weakened.
