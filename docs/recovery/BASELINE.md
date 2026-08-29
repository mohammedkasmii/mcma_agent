# BASELINE

**Baseline commit SHA:** `0290fe9df24c9e2f2b054ee4f8b14b8267f07b12`
**Branch:** `refactor/solid-architecture` (the only source of truth)
**Document phase:** Phase 2 — Recovery Documentation (documentation only; no production code, tests, dependencies or configuration were changed)
**Scope note:** No other branch was inspected. The live MCMA platform was not accessed. No session data, cookies, tokens or personal data appear in this document.

---

## 1. Overall classification (READ THIS FIRST)

> **This branch is a functional *recovery baseline*, but it is NOT production-safe for form filling.**

- The mapping, notification-extraction, session-keeper and dashboard code runs and has real, useful behaviour.
- **Live form-filling (mission writes) is unsafe and must be treated as prohibited** until the safety gates described in `SAFETY_INVARIANTS.md` are fixed. See `KNOWN_FAILURES.md` for the specific confirmed defects.
- **"Preview", "dry-run" and "safety/test mode" are NOT write-incapable in the current implementation.** They are labels and flags, not enforced capabilities. Row-level writes to the portal execute regardless. See `SAFETY_INVARIANTS.md` §Preview/Dry-run.

## 2. What the passing tests do and do not prove

**Verified:** `python -m pytest tests/ -v` → **19 passed in 0.31s** (see `TEST_EVIDENCE.md` for the exact run).

- The 19 tests prove **only** the currently tested behaviours: the Wexia→dossier **mapper** logic, the **garage-conventionné rubrique matcher** (pure function), and the **session-keeper** missing-file contract + interval constant.
- The tests **do not** prove: mission-search safety, mission-identity verification, preview/dry-run safety, browser-write safety, network interception correctness, or API security. There is **no** test for those areas (`TEST_EVIDENCE.md` §Coverage gaps).

## 3. Environment (verified)

- Python **3.14.0** (system interpreter; has `pytest 9.1.1`).
- `.venv/` present with runtime deps (`fastapi 0.141.1`, `playwright 1.62.0`, `pydantic 2.13.4`, `pymupdf 1.28.2`) but **no pytest** — tests run under the system interpreter.
- Node **v24.14.1** present but unused by this branch (no `package.json`, no build step).
- `requirements.txt` is **unpinned** (8 packages: fastapi, uvicorn, playwright, pymupdf, pydantic, requests, httpx, pytest).
- No `CLAUDE.md`, no `conftest.py`, no `pyproject.toml`/`pytest.ini`/`setup.cfg`.

## 4. Repository census (verified)

- **49 tracked files**, ~5,750 lines of Python/JS on this branch.
- Directories `api/`, `db/`, `mcma/`, `portal/`, `workflows/`, `tools/` contain **only `__pycache__`** residue — **no tracked source** on this branch.
- Tracked binaries: three PDFs under `input_documents/` (committed before the later `.gitignore` rule for `*.pdf`).
- `mcma_auth_state.json` **does not exist on disk** at baseline (never created, never opened, contents never printed).

**Working-tree status at baseline** (before Phase 2 doc creation):
```
?? MCMA_REBUILD_MASTER_PROMPT.md   (intentional, untracked instruction file)
?? data/                            (data/mcma.db — user-confirmed leftover from another branch; untouched, unopened)
```

## 5. Historical-command verification (verified against code)

| Command | Verdict | Evidence |
|---|---|---|
| `python auth_setup.py` | ✅ valid | `auth_setup.py:75-76` |
| `python get_notifications.py --headless` | ✅ valid | `get_notifications.py:75-81` |
| `python run_dossier.py --plan-only` | ❌ **flag does not exist** | `run_dossier.py:90-95` argparse defines `--json/--devis/--photos/--rapport/--reference/--matricule` only |
| `python main.py` | ✅ valid (FastAPI on `0.0.0.0:8000`) | `main.py:287` |

## 6. Phase 1 plan file (reported per instruction)

- **Exact path:** `C:\Users\hp\.claude\plans\read-mcma-rebuild-master-prompt-md-compl-playful-castle.md`
- **Contents:** the Phase 1 repository-analysis report — **instructions/documentation only**. It contains **no production-code change**. It lives under the user's global `~/.claude/plans/` directory, **outside the repository**, so it does not appear in `git status` and does not alter any tracked file.

## 7. Confirmations

- No production code, tests, dependencies or configuration were modified during Phase 1 or Phase 2.
- No branch other than `refactor/solid-architecture` was inspected.
- No live MCMA access occurred; all analysis is static.
- No secrets, cookies, tokens or personal data are exposed in any recovery document.
