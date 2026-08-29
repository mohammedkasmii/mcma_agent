# TEST EVIDENCE

**Baseline commit SHA:** `0290fe9df24c9e2f2b054ee4f8b14b8267f07b12`

Exact offline test command, verbatim result, per-file coverage, and an explicit statement of what the tests do **not** prove.

---

## 1. Safety pre-flight (verified before running)

- No test opens a browser or navigates to `sinauto.mamda-mcma.ma` (no `async_playwright`/`page.goto` reachable in the collected tests).
- `tests/test_session_keeper.py` is safe **only** because `check_session_health` returns early when the auth file is missing (`session_keeper.py:60-68`), **before** the Playwright block (`:70-76`). The guard path used is `temp/non_existent_auth.json`, verified absent on disk. *(This safety is incidental, not enforced — a filename collision would make it a live-portal test.)*
- No test reads `mcma_auth_state.json`.
- There is **no** `conftest.py`, `pytest.ini`, `pyproject.toml`, `setup.cfg` or socket guard — **no production-domain (network) blocking exists in the suite.**

## 2. Exact command and result (verified)

Command (run from the repository root):
```
python -m pytest tests/ -v
```

Result:
```
platform win32 -- Python 3.14.0, pytest-9.1.1, pluggy-1.6.0
collected 19 items

tests/test_garage_conventionne.py::test_gc_matching_exact_lib_rubrique PASSED
tests/test_garage_conventionne.py::test_gc_matching_with_aliases_and_accents PASSED
tests/test_garage_conventionne.py::test_gc_all_or_nothing_fails_closed PASSED
tests/test_garage_conventionne.py::test_gc_unique_row_assignment PASSED
tests/test_garage_conventionne.py::test_gc_logger_creates_file_and_summarizes PASSED
tests/test_mapper.py::test_1_se00009_exact_rubriques_and_totals PASSED
tests/test_mapper.py::test_2_normal_mode_not_conventionne_with_repairer PASSED
tests/test_mapper.py::test_3_approved_chiffrage_beats_submitted PASSED
tests/test_mapper.py::test_4_part_origin_aliases PASSED
tests/test_mapper.py::test_5_colle_and_labour_mappings PASSED
tests/test_mapper.py::test_6_decimal_precision_and_tax_remainder_allocation PASSED
tests/test_mapper.py::test_7_unknown_part_type_fails_closed PASSED
tests/test_mapper.py::test_8_unknown_labour_fails_closed PASSED
tests/test_mapper.py::test_9_conflicting_registrations_warning_and_review PASSED
tests/test_mapper.py::test_10_dates_formatted_dd_mm_yyyy PASSED
tests/test_mapper.py::test_11_missing_optional_fields_skipped PASSED
tests/test_mapper.py::test_12_ged_documents_remain_disabled PASSED
tests/test_session_keeper.py::test_session_health_missing_file PASSED
tests/test_session_keeper.py::test_default_interval PASSED

============================= 19 passed in 0.31s ==============================
```

- **Passed: 19 · Failed: 0 · Skipped: 0 · Warnings: 0 · Duration: 0.31s.**
- Interpreter: system Python 3.14.0 with pytest 9.1.1 (the `.venv` has no pytest).
- **Run invariant:** must be `python -m pytest` from the repo root. With no `conftest.py`/`tests/__init__.py`, bare `pytest` fails to put the root on `sys.path`, so `test_garage_conventionne.py` and `test_session_keeper.py` (which import top-level modules) will not collect. Only `test_mapper.py` self-patches `sys.path` (`:8`).

## 3. Working-tree effect (verified)

- After the run, `git status --porcelain` showed only the two known untracked entries (`MCMA_REBUILD_MASTER_PROMPT.md`, `data/`) — **no tracked file changed.**
- Side effect: `tests/test_garage_conventionne.py` writes scratch JSON under `temp/test_logs/` via a real `GCLogger` (`test_garage_conventionne.py:19-21`); `temp/` is gitignored, so this does not alter tracked files.

## 4. Per-file coverage (verified)

- **`tests/test_mapper.py` (12 tests)** — pure-logic tests of `WexiaToDossierMapper`: exact rubriques/totals, normal-vs-conventionné, approved-beats-submitted chiffrage, part-origin aliases, colle/labour mappings, Decimal precision + tax remainder, unknown part_type fails closed, unknown labour fails closed, conflicting registrations → review, DD/MM/YYYY dates, missing optional fields, GED stays disabled. No Playwright/network/auth. *Caveat:* the `se00009` fixture falls back to an inline literal when `input_dossier/dossier-se00009.json` is absent (`:13-76`), so results are environment-independent in CI but could differ if a real file exists locally.
- **`tests/test_garage_conventionne.py` (5 tests)** — the pure `match_all_rubriques` matcher: exact `LibRubrique`, alias/accent tolerance, all-or-nothing fail-closed (`[]`), unique row assignment, logger file creation. No browser/network.
- **`tests/test_session_keeper.py` (2 tests)** — missing-file health contract and `DEFAULT_INTERVAL_MINUTES == 10`. Network-capable code, kept offline by the missing-file guard only.

## 5. What these tests do NOT prove (explicit)

The 19 passing tests prove **only** the mapper logic, the garage-conventionné rubrique matcher, and the session-keeper missing-file/interval contract. They provide **no** coverage of, and therefore no assurance about:

- Mission search / selection / **identity verification** (`browser/mission_navigator.py`).
- **Preview / dry-run safety** and the **network interceptor** (`browser/safety_interceptor.py`) — the single most consequential component has **zero tests**.
- **Browser-write safety** — row-edit clicks and network awaits (`browser/mode_normal.py`, `browser/mode_conventionne.py`), including the forced charge-mutuelle path.
- Any **FastAPI route** or **API security** (`main.py`).
- The **notification extractor** (`browser/notifications.py`).
- **`mapping_status` enforcement** — there is no enforcement to test.

> The tests confirm current mapper/matcher/session-keeper behaviour. They are **not** evidence that live form-filling is safe. Per `SAFETY_INVARIANTS.md`, live form-filling remains prohibited until the safety gates are fixed and covered by tests.
