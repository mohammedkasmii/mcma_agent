# Phase 2 — Portal safety mechanics (mock server only; live writes stay disabled)

All four increments are proven against the **extended mock server** (INC-06). The write-enable gate remains **OFF**;
no live write is possible until INC-23.

---

## INC-06 — Extended mock server + portal-contract fixtures

- **Purpose/outcome:** Extend the offline `mock_server.py` replica to cover the **notification surface** and the
  **row-op endpoints** (and auth/session endpoints) the current mock lacks, plus per-request contract fixtures, so every
  Phase 2 safety test runs fully offline.
- **Why here:** the interception/identity/writer tests need a portal-shaped target that is provably not the real portal.
- **Prerequisites:** INC-01 (egress), INC-03 (skeleton).
- **Addresses:** PORTAL_CONTRACT §7/§8; TEST_STRATEGY integration; supports INC-07..09, INC-14.
- **Baseline files modified/retired:** `mock_server.py` extended (it is a test/dev harness, not production runtime; safe
  to modify — it is not part of the shipped service). New fixtures added.
- **Target modules/files introduced:** extend `mock_server.py` (add `/expertise/notification/alerte`,
  `getAlerte/CodeAlerte/{code}`, `#listeAlerte` DataTable, `updateDevisDet`, `createRapportDefDet`, login/OTP/session,
  final endpoints for block-testing); `tests/fixtures/contracts/*.json` (reviewed request/response tuples).
- **DB migration impact:** none.
- **Dependency/config impact:** none (uses existing FastAPI for the mock; served on loopback only).
- **Feature flags/adapters:** none.
- **Out-of-scope:** the real portal contract (that is confirmed only in INC-23 via approved evidence).
- **Tests-first:** `test_mock_server_serves_notification_datatable`; `test_mock_server_row_endpoints_exist`;
  `test_mock_server_binds_loopback_only`.
- **Initial failing-test expectation:** fail (endpoints absent in the mock).
- **Mock/fixtures:** this increment *builds* the fixtures.
- **Implementation steps:** add notification routes + DataTable HTML → add row-op routes → add auth/session/final routes →
  encode reviewed contract tuples as fixtures.
- **Acceptance criteria:** mock serves the full surface on loopback; contract fixtures load; no external CDN dependency in
  test mode (bundle jQuery/Bootstrap locally or stub) so tests run air-gapped.
- **Safe offline verification:** `python -m pytest tests/mock -v`.
- **Safety gates:** none new; enabler for G2.
- **Expected git-diff scope:** `mock_server.py`, `tests/fixtures/contracts/`, `tests/mock/`.
- **Rollback:** revert the mock extensions.
- **Risks/failure behavior:** mock drift from the real portal is acceptable here — the real contract is confirmed
  separately (INC-23); the mock encodes *our expected* contract for safety tests.
- **Definition of Done:** full offline surface; loopback-only; CDN-free test mode.
- **Approval boundary:** stop before INC-07.

---

## INC-07 — Context-level default-deny interception + permanent final-endpoint block

- **Purpose/outcome:** The `portal` module installs interception at the **BrowserContext** level with **contract-based
  default-deny** and a permanent, un-disableable final-endpoint **abort** (never fake-200).
- **Why here:** this is the foundational network safety every capability relies on; it must exist before any read/write.
- **Prerequisites:** INC-06.
- **Addresses:** ADR-0004; SAFETY_MODEL §3; INV-3, INV-4; F8 (fail-open), F9 (page-scoped).
- **Baseline files modified/retired:** none retired; baseline `browser/safety_interceptor.py` remains until INC-22. New
  `portal` interceptor is separate and correct.
- **Target modules/files introduced:** `portal/interception.py` (contract tuple matcher `(host, route, method, payload
  shape, capability, operation-type)`; `service_workers="block"`; WS blocked; external-domain block; handler-exception →
  abort), `portal/final_endpoints.py` (permanent blocklist). Tests under `tests/portal/safety/`.
- **DB migration impact:** none.
- **Dependency/config impact:** playwright (already present); `portal` is the sole importer.
- **Feature flags/adapters:** a **write-enable gate** config exists but defaults **OFF** and is not a bare boolean — it
  requires confirmed contract records + passing safety tests (checked in INC-23). Read interception is always on.
- **Out-of-scope:** capabilities themselves (INC-08); identity (INC-09).
- **Tests-first (safety):**
  - **`test_unknown_request_is_aborted`** (GET included — a GET not in a read contract is denied).
  - **`test_final_endpoints_abort_not_fulfilled`** (never returns fake `200 success`).
  - `test_route_handler_exception_aborts` (fail-closed on handler error).
  - `test_service_workers_blocked` and `test_websocket_blocked` and `test_external_domain_blocked`.
  - `test_interception_is_context_scoped` (a popup/new page is covered).
- **Initial failing-test expectation:** all fail (module absent).
- **Mock/fixtures:** INC-06 mock + contract fixtures.
- **Implementation steps:** context route handler → default-deny → contract match → final-endpoint permanent abort →
  service-worker/WS/external-domain blocks → handler-exception abort.
- **Acceptance criteria:** all safety tests green; final block cannot be disabled by any flag/mode.
- **Safe offline verification:** `python -m pytest tests/portal/safety -v`.
- **Safety gates:** contributes to **G2**.
- **Expected git-diff scope:** `portal/interception.py`, `portal/final_endpoints.py`, `tests/portal/safety/`.
- **Rollback:** the new interceptor is unused by baseline; delete to revert.
- **Risks/failure behavior:** any unmatched request fails closed (aborted); the safety property is the default.
- **Definition of Done:** INV-3/INV-4 tests green; fake-200 path impossible.
- **Approval boundary:** stop before INC-08.

---

## INC-08 — `ReadCapability` + `LoginCapability` (LeaseHandle; no writes)

- **Purpose/outcome:** Construct the two non-write capabilities. `ReadCapability` exposes search/open/scrape/read_rows;
  `LoginCapability` allows only auth/session contracts. Both receive a `LeaseHandle` (from `execution`/`persistence`
  later) and never import persistence/sqlite.
- **Why here:** dry-run and all reads run through `ReadCapability`; onboarding uses `LoginCapability`; both precede the writer.
- **Prerequisites:** INC-07.
- **Addresses:** ADR-0003; SAFETY_MODEL §1; INV-1 (structural: no writer path); correction #5 (LeaseHandle threading).
- **Baseline files modified/retired:** none retired.
- **Target modules/files introduced:** `portal/capabilities.py` (`ReadCapability`, `LoginCapability`, `LeaseHandle`
  protocol), `portal/session.py` (open a context with a supplied storage-state, read-only route policy). Tests under
  `tests/portal/`.
- **DB migration impact:** none (LeaseHandle is a protocol; the real lease arrives in INC-11).
- **Dependency/config impact:** none new.
- **Feature flags/adapters:** `LeaseHandle` is injected; in Phase-2 tests a stub handle is used.
- **Out-of-scope:** the writer (INC-09); real leases (INC-11); real vault (INC-13).
- **Tests-first:**
  - **`test_read_capability_has_no_write_method`** (introspection: no write surface).
  - **`test_read_capability_cannot_be_upgraded_to_writer`** (no code path).
  - `test_login_capability_allows_only_auth_session_contracts` and `test_login_capability_denies_row_and_final_endpoints`.
  - `test_portal_does_not_import_persistence_or_sqlite` (import contract).
- **Initial failing-test expectation:** fail (module absent).
- **Mock/fixtures:** INC-06 mock; stub `LeaseHandle`.
- **Implementation steps:** LeaseHandle protocol → ReadCapability (read route policy) → LoginCapability (auth route policy).
- **Acceptance criteria:** read/login capabilities behave; no write method exists; import contract green.
- **Safe offline verification:** `python -m pytest tests/portal -v`.
- **Safety gates:** contributes to **G2** (dry-run structurally write-incapable).
- **Expected git-diff scope:** `portal/capabilities.py`, `portal/session.py`, `tests/portal/`.
- **Rollback:** delete the new capability module.
- **Risks/failure behavior:** any attempt to write via a read capability is a type/attribute error at author time.
- **Definition of Done:** INV-1 structural tests green.
- **Approval boundary:** stop before INC-09.

---

## INC-09 — Mission search + identity gate + TOCTOU + exact-IdRubrique + `VerifiedMissionWriter` mechanics

- **Purpose/outcome:** Implement `portal.open_verified_writer(lease_handle, expected_identity)`: exactly-one search,
  open, **two-tier identity verify (registration mandatory)** in the **same context**, exact-`IdRubrique` row selection,
  read-before/diff-before/verify-after row ops, TOCTOU re-verify — with **charge-mutuelle never written**. Live writes
  remain disabled by the write-enable gate.
- **Why here:** the write mechanics + all write-safety gates converge here; must be proven before jobs/leases wire them.
- **Prerequisites:** INC-05 (ExpectedIdentity/plan), INC-08 (capabilities).
- **Addresses:** ADR-0003/0004; SAFETY_MODEL §1/§4/§4a/§6; INV-2, INV-6, INV-8; F3/F4/F5 (mission selection), F6 (forced
  charge-mutuelle), F7 (duplicate checkmark), F16 (rubrique-row selection).
- **Baseline files modified/retired:** none retired; baseline `browser/mission_navigator.py`, `mode_normal.py`,
  `mode_conventionne.py` remain until INC-22. New `portal` writer is separate.
- **Target modules/files introduced:** `portal/identity.py` (two-tier gate), `portal/mission.py` (search exactly-one +
  open), `portal/writer.py` (`VerifiedMissionWriter`: `read_row`/`write_row`/`verify_row`/`trigger_native_recalc`;
  exact-`IdRubrique`; RBW/DBW/VAW). Tests under `tests/portal/writer/`.
- **DB migration impact:** none.
- **Dependency/config impact:** none new.
- **Feature flags/adapters (review SEC-3 — structural, not a flag):** mock-writes are permitted **only** because the
  reviewed contract tuple's **host is loopback** — never by a global "mock mode"/`TEST_MODE`-style flag. A non-loopback
  host can never be write-allowed while the write-enable gate is OFF. This avoids re-creating the `TEST_MODE` cliff.
- **Out-of-scope:** durable jobs/leases (Phase 3); enabling live writes (INC-23).
- **Tests-first (safety):**
  - identity: **`test_zero_match_fails_closed`**, **`test_multiple_match_fails_closed`**, **`test_registration_plate_alone_insufficient`**, `test_missing_registration_fails_closed`, `test_contradictory_identifiers_fail_closed`, `test_toctou_reverify_before_first_write_and_after_navigation`.
  - rubrique: **`test_row_selected_by_exact_IdRubrique`**, **`test_zero_or_multiple_rubrique_rows_fail_closed`**, `test_label_substring_and_first_row_and_positional_fallback_rejected`.
  - write mechanics: `test_read_before_write_diff_skips_unchanged`, `test_verify_after_write_mismatch_aborts`, `test_single_write_no_duplicate_checkmark`.
  - **`test_charge_mutuelle_fields_never_written`** (mutuelle/societaire never in any write; only native recalc invoked).
  - **`test_dry_run_never_constructs_writer`** (execution path check).
  - **`test_no_non_loopback_host_write_allowed_while_gate_off`** (SEC-3: only a loopback contract host may be write-allowed
    while the write-enable gate is OFF; any live/non-loopback write target is aborted).
- **Initial failing-test expectation:** all fail (module absent).
- **Mock/fixtures:** INC-06 mock with the mission/row surface; identity fixtures with matching/mismatching identifiers.
- **Implementation steps:** identity gate → search exactly-one → open in one context → verify all → exact-IdRubrique row
  op → RBW/DBW/VAW → TOCTOU re-verify → assert charge-mutuelle unreachable.
- **Acceptance criteria:** every write-safety property green against the mock; **no live write possible** (write-enable
  gate OFF, verified by a test that a live-host write is aborted by interception).
- **Safe offline verification:** `python -m pytest tests/portal/writer -v`.
- **Safety gates:** **G2** (phase gate) — dry-run has no writer; final endpoints abort; unknown requests fail closed;
  identity/rubrique fail closed; charge-mutuelle never written — all proven, **live writes still disabled**.
- **Expected git-diff scope:** `portal/identity.py`, `portal/mission.py`, `portal/writer.py`, `tests/portal/writer/`.
- **Rollback:** delete the new writer modules; baseline navigator untouched.
- **Risks/failure behavior:** every ambiguity fails closed (no write). The writer cannot reach a live host (interception).
- **Definition of Done:** G2 satisfied; INV-2/6/8 + F3/4/5/6/7/16 tests green.
- **Approval boundary:** stop; **Gate 2 review** before Phase 3.
