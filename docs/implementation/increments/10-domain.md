# Phase 1 — Project structure & pure domain

---

## INC-03 — Project config + module skeleton + dependency contract

- **Purpose/outcome:** Establish the modular-monolith package layout and an **enforceable** dependency-direction contract
  so purity is a test, not a convention.
- **Why here:** must precede any module code (ADR-0001, MODULE_BOUNDARIES).
- **Prerequisites:** INC-02.
- **Addresses:** ADR-0001; MODULE_BOUNDARIES §1–§4; F28 (duplicated constants → single `mcma.core.config`).
- **Collision-free migration strategy (correction #4 — exact, not left to the implementer):** the repository **already
  contains** top-level `core/`, `browser/`, `mapper/`, `main.py`, `mock_server.py`. To avoid name collisions, **all new
  modules live under a single top-level package `mcma/`**: `mcma/core`, `mcma/domain`, `mcma/mapping`, `mcma/planning`,
  `mcma/persistence`, `mcma/portal`, `mcma/execution`, `mcma/notifications`, `mcma/app`. The legacy top-level `core/`,
  `browser/`, `mapper/`, `main.py`, `mock_server.py` are **left untouched** (except INC-00's write-removal) until INC-22
  retirement. Wherever a later increment writes a path like `domain/x.py` it means **`mcma/domain/x.py`**.
- **Ownership rules (enforced by the import contract):**
  - `mcma.portal` is the **only** module that may import `playwright`; `mcma.persistence` the only one importing `sqlite3`;
    `mcma.app` the only one importing `fastapi`; `mcma.domain`/`mcma.mapping`/`mcma.planning` import no I/O libs.
  - **Temporary legacy allowlist:** the baseline top-level `core`, `browser`, `mapper`, `main`, `mock_server` are exempt
    from the final ownership rule (they may import playwright etc.) — the contract does **not** require them to comply
    until they are retired in INC-22. `mock_server` is tagged **test infrastructure** (loopback-only), not production.
  - **No new module may import a legacy package** (one-way: legacy is allowed to exist, but `mcma.*` never depends on it).
  - **INC-22 tightens the contract:** the legacy allowlist is deleted and the final ownership rule applies with no exceptions.
- **Baseline files modified/retired:** none retired here; the `mcma/` packages are created alongside the (write-contained)
  baseline read paths.
- **Target modules/files introduced:** `mcma/` package skeleton (`mcma/<module>/__init__.py` for the nine modules);
  **`mcma/core/config.py`** (typed settings; the DB path and all runtime settings come from `mcma.core.config`);
  `pyproject.toml` (holds the `[tool.pytest.ini_options]`, `import-linter`, and `uv` config — **pytest configuration
  lives in `pyproject.toml` only**, no `pytest.ini`/`setup.cfg`); **top-level** `tests/contracts/test_import_boundaries.py`
  (import-linter contracts) + `tests/plan/test_roadmap_prereqs_match_graph.py`. All tests live under top-level `tests/*`.
- **DB migration impact:** none.
- **Dependency/config impact:** dev-only **import-linter** (chosen tool — correction #6) with contracts in `pyproject.toml`;
  `ruff`/`ty` as non-breaking dev tools. See README §Implementation choices for the resolved toolchain.
- **Feature flags/adapters:** none.
- **Out-of-scope:** any business logic (INC-04+).
- **Tests-first:**
  - `test_domain_imports_no_io` — importing `mcma.domain`/`mcma.mapping`/`mcma.planning` must not transitively import
    `playwright`, `sqlite3`, `fastapi`, `httpx`, `requests`.
  - `test_single_owner_playwright_sqlite_fastapi` — only `mcma.portal` imports playwright; only `mcma.persistence` imports
    sqlite3; only `mcma.app` imports fastapi (legacy `main.py`/`browser/*` are on the temporary allowlist until INC-22).
  - `test_no_dependency_cycles` — the module graph is acyclic and one-directional.
  - **`test_roadmap_prereqs_match_graph`** (corrections #2/#6 drift check) — for each increment it extracts the
    **normalized set of canonical `INC-XX` identifiers** from the single `**Prerequisites:**` line (the field contains
    **only** `INC-XX` tokens and `none`; any human rationale lives on the separate `**Prerequisite rationale:**` line and
    is ignored), from the canonical dependency table in `REBUILD_ROADMAP.md`, and from the Mermaid graph edges; it asserts
    all three normalized sets are **identical for all 24 increments**. Because the field is single-line and token-only, no
    multiline wrapping can cause an INC ID to be missed. Runs in CI so the plan cannot silently drift.
- **Initial failing-test expectation:** fails (packages/contract absent).
- **Mock/fixtures:** none.
- **Implementation steps:** create package skeleton → author import-linter contract from MODULE_BOUNDARIES → wire into
  `python -m pytest` → add `mcma/core/config.py` typed settings stub (no secrets).
- **Acceptance criteria:** contract tests green; skeleton importable; baseline scripts still run unchanged.
- **Safe offline verification:** `python -m pytest tests/contracts -v`; **`lint-imports`** (mandatory — import-linter is
  a required CI/verification command, run on every increment).
- **Safety gates:** contributes to G1.
- **Expected git-diff scope:** new packages + `pyproject.toml` + `tests/contracts/`. No baseline `.py` edits.
- **Rollback:** delete new packages/config; baseline untouched.
- **Risks/failure behavior:** none to runtime (skeleton only).
- **Definition of Done:** boundaries enforced by a passing test; documented in code as the contract.
- **Approval boundary:** stop before INC-04.

---

## INC-04 — Pure domain: value objects, enums, normalization, Money, business rules

- **Purpose/outcome:** Implement the pure, deterministic domain: `Money`(Decimal), `RegistrationPlate`, identifiers,
  the enums, the shared normalizer, and the corrected classification rules — all with property tests.
- **Why here:** everything downstream (planning, writer, tests) depends on these types and rules.
- **Prerequisites:** INC-03.
- **Addresses:** DOMAIN_MODEL §1–§5; BUSINESS_RULES B.1/B.2/**B.4**/B.6/B.7; INV-6, INV-7; F13 (glass→1),
  F14 (out-of-catalogue — B.4 fail-closed), F15 (`"mo"` token), F17 (negative TVA), F33 (keyword family inference).
- **Baseline files modified/retired:** none retired. This is the corrected re-implementation of the mapper's rule core;
  the baseline `mapper/wexia_mapper.py` remains until INC-22 parity.
- **Target modules/files introduced:** `core/money.py`, `domain/values.py`, `domain/enums.py`, `domain/normalize.py`,
  `domain/rubriques.py` (catalog + three-origin + glass component×operation + labour structured-first + colle),
  `domain/results.py` (`Mapped`/`NeedsReview(reason_code)`). Tests under `tests/domain/` + `tests/domain/property/`.
- **DB migration impact:** none.
- **Dependency/config impact:** dev-only `hypothesis`.
- **Feature flags/adapters:** none (pure library; not wired to any run path yet).
- **Out-of-scope:** reading Wexia input (INC-05); building plans (INC-05).
- **Tests-first (property + example):**
  - money: `test_money_is_decimal_half_up`; `test_tax_remainder_allocation_sums_to_0_01`; **`test_negative_line_tva_fails_closed`** → `NeedsReview(INVALID_TAX_ALLOCATION)` (no clamp/redistribute).
  - origin: `test_three_origin_maps_1_2_3`; **`test_no_keyword_inference_of_4_6_or_13_15`**; `test_unknown_part_origin_fails_closed`.
  - glass: property over component×operation → 19–24; **`test_glass_requires_component_and_operation`**;
    `test_ambiguous_or_conflicting_glass_fails_closed`; `test_part_type_never_used_for_glass_family`.
  - labour: `test_structured_item_type_operation_type_decides_family`; **`test_generic_peinture_mecanique_electrique_alone_insufficient`**; `test_no_unrestricted_mo_substring`; `test_unknown_or_contradictory_labour_fails_closed`.
  - colle/kits: `test_colle_25_kit_26_kit_vitre_27`.
  - normalize: property `test_normalize_idempotent_accents_punct_ws`.
  - out-of-catalogue: `test_out_of_catalogue_rubric_id_fails_closed`.
- **Initial failing-test expectation:** all fail (module absent).
- **Mock/fixtures:** none (pure).
- **Implementation steps:** `Money` → normalizer → enums → origin classifier → glass classifier → labour classifier →
  colle → result algebra; each red→green→refactor per test.
- **Acceptance criteria:** every rule from BUSINESS_RULES §B is enforced fail-closed; property tests pass with a bounded
  example budget; the INC-02 goldens that captured defects (glass→1, `"mo"`) are updated here with a documented diff.
- **Safe offline verification:** `python -m pytest tests/domain -v`.
- **Safety gates:** G1 (fail-closed mapping).
- **Expected git-diff scope:** `core/money.py`, `domain/*`, `tests/domain/*`. No baseline mapper edit.
- **Rollback:** delete `domain/*` + tests; baseline mapper unaffected.
- **Risks/failure behavior:** a rule gap surfaces as a failing property test (fail-closed by design).
- **Definition of Done:** all domain tests green; INC-02 defect-goldens intentionally revised with a recorded rationale.
- **Approval boundary:** stop before INC-05.

---

## INC-05 — Typed Wexia input boundary → deterministic `ProposedPlan`

- **Purpose/outcome:** Parse/validate Wexia input into typed structures and build a **deterministic** `ProposedPlan`
  (pure data; no `mode`/`read_only`; `NeedsReview` blocks writeability). Same input → identical `plan_hash`.
- **Why here:** the plan is the reviewable artifact every write path consumes; must exist before job orchestration.
- **Prerequisites:** INC-04.
- **Addresses:** DOMAIN_MODEL §6; ADR-0002; F11 (`mapping_status` unused → `NeedsReview` now blocks writes); INV-6/7.
- **Baseline files modified/retired:** none retired (baseline mapper stays until INC-22).
- **Target modules/files introduced:** `mapping/wexia.py` (typed input model + normalization boundary; structured
  `item_type`/`operation_type`/`labor_type_id` first), `planning/plan.py` (`ProposedPlan`, `RowOp`, `ExpectedIdentity`,
  `plan_hash`), `planning/registry.py` (`WorkflowRegistry`). Tests under `tests/planning/`.
- **Repair-workflow invariants (G1 — `PORTAL_ROW_WORKFLOWS.md`, `WORKFLOW_STATE_MODEL.md` §2):**
  - `RepairWorkflow` is a typed domain enum: `{MODE_NORMAL, GARAGE_CONVENTIONNE}`.
  - `ProposedPlan.repair_workflow` carries it as capability-neutral structural plan data.
  - **Two deterministic builders** — one per repair workflow — registered under distinct registry names.
  - `repair_workflow` is **included in the canonical serialization and `plan_hash`** (two otherwise-identical plans with
    different workflows hash differently).
  - Plans contain **no DRY_RUN/EXECUTE authorization** (no `mode`/`read_only`; `repair_workflow` is not authorization).
  - **Both builders and their registry names are tested.**
- **DB migration impact:** none.
- **Dependency/config impact:** pydantic (already present) for the typed boundary.
- **Feature flags/adapters:** none (no run path yet).
- **Out-of-scope:** persistence; execution; any portal contact.
- **Tests-first:**
  - **`test_plan_is_deterministic_same_input_same_hash`** (property: shuffling input line order yields identical plan/hash).
  - `test_plan_has_no_mode_or_read_only_field`.
  - `test_needs_review_line_makes_plan_non_writeable`.
  - `test_expected_identity_requires_registration_plate` (mandatory; ref/idSinistre at least one).
  - `test_rowop_has_no_charge_mutuelle_field`.
  - `test_reform_and_conflicting_modes_fail_closed` (carry over baseline fail-closed cases).
  - `test_plan_hash_includes_repair_workflow` (same rows, different `repair_workflow` → different `plan_hash`).
  - builder/registry tests: both deterministic builders exist, are registered under their distinct names, and each
    produces a plan whose `repair_workflow` matches its registry entry.
- **Initial failing-test expectation:** all fail (modules absent).
- **Mock/fixtures:** sanitized Wexia JSON fixtures (no PII).
- **Implementation steps:** typed input model → normalization boundary → deterministic plan builder (stable sort by
  rubrique_id then first source pointer) → `plan_hash` (sha256 of canonical serialization) → registry.
- **Acceptance criteria:** determinism proven; plan is pure data; `ExpectedIdentity` enforces mandatory registration;
  any `NeedsReview` yields a non-writeable plan; `repair_workflow` typed, hashed, capability-neutral, and covered by the
  builder/registry tests above.
- **Safe offline verification:** `python -m pytest tests/planning -v`.
- **Safety gates:** **G1** (domain+planning pure, deterministic, fail-closed) — phase gate to Phase 2.
- **Expected git-diff scope:** `mapping/*`, `planning/*`, `tests/planning/*`.
- **Rollback:** delete `mapping/*` + `planning/*` + tests.
- **Risks/failure behavior:** non-determinism surfaces as a failing property test.
- **Definition of Done:** G1 satisfied; determinism + purity + fail-closed all green.
- **Approval boundary:** stop; Gate 1 review before Phase 2.
