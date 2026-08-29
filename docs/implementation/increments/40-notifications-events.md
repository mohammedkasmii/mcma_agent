# Phase 4 — Notifications & events

---

## INC-14 — Notification extraction + category-scoped three-poll lifecycle + session-refresh poller

- **Purpose/outcome:** Port the working extraction (`length=-1` AJAX + DataTable fallback) into the `notifications`
  module writing to persistence, with **category-scoped** presence and the **three-poll** lifecycle driven by
  `poll_run_categories` (a category advances only when *that* category completed under a valid session). **This increment
  also owns the replacement for the baseline session keep-alive daemon (review TR-F31):** a scheduled **session-refresh
  poller** that runs under the per-account lease (INC-11), validates/refreshes each account session, and escalates on
  repeated failure via the health/observability surface (INC-20) — replacing the unscheduled, no-escalation baseline keeper.
- **Why here:** the dashboard read path and SSE depend on persisted, correctly-scoped presence.
- **Prerequisites:** INC-08 (ReadCapability), INC-10 (persistence), INC-11 (lease — for the session-refresh poller),
  INC-13 (session vault — the poller refreshes real sessions).
- **Addresses:** ADR-0006; SYSTEM_OVERVIEW/WORKFLOW_CATALOG (W2); BUSINESS_RULES B.9; INV-9 (read-only, no mutation);
  **F31** (session keep-alive: scheduled + escalation via the poller); F27 (demo-data confusion is fixed in the dashboard,
  INC-19; extraction is truthful here).
- **Baseline files modified/retired:** none retired; baseline `browser/notifications.py` + `get_notifications.py` stay
  until parity (INC-22). New extractor is separate and persists to the DB.
- **Target modules/files introduced:** `notifications/extract.py` (via `ReadCapability`), `notifications/presence.py`
  (per-`(account,claim,category)` lifecycle; complete-valid-poll rule), `notifications/staging.py` (idSinistre-less →
  `unmatched_notifications`). Tests under `tests/notifications/`.
- **DB migration impact:** uses claims/categories/category_presence/poll_runs/poll_run_categories/unmatched_notifications.
- **Dependency/config impact:** none new.
- **Feature flags/adapters:** a flag selects DB-backed vs legacy-JSON read for the dashboard; DB path proven before cutover (INC-22).
- **PII protection (correction #3 — chosen sequence B):** INC-14 is **fixture/mock-only for real claimant data**. Its
  logic (extraction, category-scoped lifecycle, staging, poller) is developed and tested entirely against **sanitized/
  synthetic** fixtures. **No production notification/session/claim PII may be persisted until the Production-Data-Readiness
  gate (G-PDR) passes** (`RELEASE_GATES.md`), which requires INC-20 (PII-safe logging + screenshots) and INC-21 (DB outside
  served dir + BitLocker/SQLCipher + strict NTFS ACL + encrypted backup) to be green. Enabling production ingestion is a
  later flip gated on G-PDR, not part of INC-14.
- **Out-of-scope:** SSE (INC-15); dashboard rendering (INC-19); **any persistence of real production PII** (deferred to the G-PDR flip).
- **Tests-first:**
  - **`test_absence_increments_only_when_that_category_complete_and_valid`**; `test_partial_or_failed_category_does_not_touch_counter`; `test_other_category_failure_never_affects_this_category`.
  - `test_three_consecutive_complete_absences_resolve_on_portal`; `test_reappearance_resets_to_active`.
  - **`test_notification_without_idSinistre_goes_to_staging_not_claims`**.
  - `test_extraction_is_read_only` (no mutating request issued).
  - **`test_reapplying_same_poll_run_is_idempotent`** (review SR-6: re-processing the same `(poll_run_id, category)` cannot
    double-advance `consecutive_absence_count`; "three consecutive" means three **distinct** complete polls, tracked via
    `last_complete_poll_version`).
  - **`test_session_refresh_poller_runs_under_lease_and_escalates_on_repeated_failure`** (TR-F31; replaces the baseline keeper).
- **Initial failing-test expectation:** fail (modules absent).
- **Mock/fixtures:** INC-06 mock notification surface + saved DataTable fixtures (sanitized).
- **Implementation steps:** extract via ReadCapability → upsert claims (NOT NULL idSinistre; else staging) → record
  `poll_run_categories` → apply per-category lifecycle → tests.
- **Acceptance criteria:** category-scoped lifecycle exactly per ADR-0006; staging enforced; read-only proven.
- **Safe offline verification:** `python -m pytest tests/notifications -v`.
- **Safety gates:** none new; correctness gate for the read path.
- **Expected git-diff scope:** `notifications/*`, `tests/notifications/*`.
- **Rollback:** flag back to legacy-JSON read; delete new module.
- **Risks/failure behavior:** an incomplete/failed poll is ignored for lifecycle (no false RESOLVED).
- **Definition of Done:** lifecycle + staging + read-only tests green.
- **Approval boundary:** stop before INC-15.

---

## INC-15 — Transactional outbox + state versions + SSE (global cursor, retention, resync)

- **Purpose/outcome:** Emit outbox events atomically with each state change; expose an SSE stream per account keyed by
  the **global `event_id`** cursor; bounded time/count retention; **snapshot + delta** recovery with forced full resync
  when the cursor predates retention; **re-check an injected `Authorizer` on each event / periodically** (the *real*
  authenticated authorizer and revocation are wired in INC-17 — correction #9).
- **Why here:** live dashboard updates depend on it; it consumes persistence. **Auth does not yet exist** (INC-16/17 come
  later), so INC-15 depends only on an **injected `Authorizer` interface**, avoiding a circular dependency.
- **Prerequisites:** INC-10, INC-14.
- **Addresses:** ADR-0009; DATA_MODEL §7/§8; API_CONTRACTS §5.
- **Baseline files modified/retired:** none (baseline has no SSE).
- **Injected interface (correction #9):**
  ```text
  # defined in mcma.app.sse, implemented for real in INC-17:
  class Authorizer(Protocol):
      def visible_accounts(self, principal) -> set[AccountId]: ...     # which accounts this principal may see now
      def is_authorized(self, principal, account_id) -> bool: ...      # re-checked per event / periodically
  ```
  INC-15 tests inject a **stub `Authorizer`**; INC-15 never imports auth.
- **Target modules/files introduced:** `mcma/persistence/outbox.py`, `mcma/app/sse.py` (per-account stream,
  `Last-Event-ID` replay, snapshot resync, retention cleanup, `Authorizer`-driven filtering). Tests under `tests/app/sse/`.
- **DB migration impact:** uses `event_outbox` (global autoincrement id), `account_state_version`.
- **Dependency/config impact:** **`sse-starlette`** (`EventSourceResponse`) — resolved choice (README §Implementation choices).
- **Feature flags/adapters:** SSE filtering uses the injected `Authorizer`; the endpoint is mounted behind real auth in INC-17.
- **Out-of-scope:** the auth wrapping (INC-17) beyond a stubbed authorizer.
- **Tests-first:**
  - **`test_outbox_event_written_in_same_transaction_as_state_change`**.
  - `test_sse_cursor_is_global_event_id`; `test_reconnect_replays_events_after_cursor_authorization_filtered`.
  - **`test_cursor_older_than_retention_forces_full_snapshot_resync`**.
  - `test_retention_bounded_by_time_and_count_not_by_idle_client_cursor`.
  - `test_stream_filters_by_injected_authorizer` (stub `Authorizer`; the *real* authenticated revocation test lives in
    INC-17 — `test_sse_revocation_drops_stream_with_real_auth`).
- **Initial failing-test expectation:** fail (modules absent).
- **Mock/fixtures:** temp DB seeded with outbox events; a stub authorizer.
- **Implementation steps:** outbox writer (same tx) → SSE publisher (per account) → reconnect replay + snapshot → retention cleanup → authz revalidation.
- **Acceptance criteria:** ordering + recovery correct; retention independent of idle clients; authz enforced live.
- **Safe offline verification:** `python -m pytest tests/app/sse -v`.
- **Safety gates:** none new.
- **Expected git-diff scope:** `persistence/outbox.py`, `app/sse.py`, tests; `pyproject` (sse dep).
- **Rollback:** disable the SSE route; outbox is harmless if unread.
- **Risks/failure behavior:** a missed/over-shared event is prevented by the global cursor + authz filter; a stale cursor forces safe resync.
- **Definition of Done:** SSE recovery + retention + authz tests green.
- **Approval boundary:** stop before INC-16.
