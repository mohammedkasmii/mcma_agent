# Phase 5 — API, authentication, authorization, TLS

---

## INC-16 — Local auth (Argon2id, AuthProvider), sessions, CSRF, permissions, secure bootstrap

- **Purpose/outcome:** Server-side authentication behind an `AuthProvider` seam: local users + Argon2id, secure
  server-side sessions (HttpOnly/SameSite/Secure), CSRF, the permission enum + role map, and a **secure first-admin
  bootstrap** (local-only, single-use, expiring; a LAN caller can never claim it).
- **Why here:** every account-scoped endpoint depends on identity; must precede endpoint exposure.
- **Prerequisites:** INC-10 (users/roles tables).
- **Addresses:** ADR-0008; API_CONTRACTS §2/§3; INV-11; F18 (unauthenticated API), F24 (auth fail-open).
- **Baseline files modified/retired:** none retired; baseline `main.py` endpoints stay until parity (they are unauth and
  will be retired in INC-22 after the new API reaches parity).
- **Target modules/files introduced:** `app/auth/provider.py` (`AuthProvider`, `LocalUserAuthProvider`),
  `app/auth/passwords.py` (Argon2id), `app/auth/sessions.py`, `app/auth/csrf.py`, `app/auth/permissions.py` (enum + role
  map), `app/auth/bootstrap.py`. Tests under `tests/app/auth/`.
- **DB migration impact:** uses `users`, `role_permissions`.
- **Dependency/config impact:** `argon2-cffi` (new runtime dep, justified). No default credentials.
- **Feature flags/adapters:** the new API is mounted on a separate path/app until parity; the legacy unauth API stays
  until INC-22. **Footgun guard (review SE-2 — hard requirement, not optional):** during migration the legacy unauth API
  MUST be bound to **loopback only** (never `0.0.0.0`) and the `profile=any` firewall rule removed, so the F18
  unauthenticated-LAN-exposure never persists while the new API is being brought up.
- **Out-of-scope:** per-account authz (INC-17); TLS (INC-18).
- **Tests-first:**
  - `test_argon2id_hash_and_verify`; **`test_no_default_credentials_exist`**.
  - `test_session_cookie_httponly_samesite_strict`; **`test_session_cookie_secure_attribute`** (review AR-L1);
    `test_csrf_required_on_state_changing_requests`.
  - **`test_session_idle_and_absolute_expiry`** and **`test_logout_invalidates_server_session`** (review AR-M1).
  - `test_permission_enum_values` and `test_viewer_role_has_no_mutation_permission`.
  - **`test_auth_provider_seam_substitutable`** (review AR-L2: a second provider can be injected; domain/workflow never
    references the concrete provider — complements the INC-03 import contract).
  - **`test_first_admin_bootstrap_rejects_non_loopback`**; `test_bootstrap_single_use_and_expires`;
    `test_bootstrap_disabled_after_first_admin_exists`.
- **Initial failing-test expectation:** fail (modules absent).
- **Mock/fixtures:** temp DB; a TestClient.
- **Implementation steps:** password hashing → provider seam → sessions → CSRF → permissions → bootstrap (loopback-only, single-use, expiring).
- **Acceptance criteria:** auth core green; no default creds; bootstrap not reachable from the LAN.
- **Safe offline verification:** `python -m pytest tests/app/auth -v`.
- **Safety gates:** contributes to **G4**.
- **Expected git-diff scope:** `app/auth/*`, tests; `pyproject` (argon2).
- **Rollback:** the new auth app is separate; unmount to revert.
- **Risks/failure behavior:** auth failures are explicit (no silent success); bootstrap fails closed off-loopback.
- **Definition of Done:** auth + bootstrap tests green.
- **Approval boundary:** stop before INC-17.

---

## INC-17 — Per-account authorization + server-derived audit + typed errors + endpoints

- **Purpose/outcome:** Enforce `user_account_access` on notifications/jobs/sessions/SSE; derive the audit actor from the
  session; return typed non-sensitive errors (no raw `str(e)`, no HTTP-200-on-failure); expose the typed endpoints incl.
  **`POST /jobs/dry-runs`** and **`POST /jobs/{dry_run_job_id}/executions`** (no `mode` field).
- **Why here:** wires auth (INC-16) + jobs (INC-12) + SSE (INC-15) into the real API surface.
- **Prerequisites:** INC-12, INC-15, INC-16.
- **Addresses:** ADR-0008; API_CONTRACTS §3/§4/§6; INV-11; F19 (error leakage), F20 (200-on-failure); correction #3
  (direct EXECUTE impossible).
- **Baseline files modified/retired:** none retired; parity/retirement of legacy `main.py` API is INC-22.
- **Target modules/files introduced:** `app/api/*.py` (routers: auth, notifications, accounts, sessions, jobs, events,
  health), `app/api/errors.py` (typed problem responses + correlation id), `app/api/authz.py` (permission + per-account
  checks). Tests under `tests/app/api/`.
- **DB migration impact:** uses `user_account_access`, `automation_jobs`, `audit_events`.
- **Dependency/config impact:** none new.
- **Feature flags/adapters:** new API mounted; legacy stays loopback-only until INC-22.
- **Out-of-scope:** TLS (INC-18); enabling live writes (INC-23) — `POST executions` creates an EXECUTE job whose live
  write remains disabled by the write-enable gate.
- **Tests-first:**
  - **`test_global_permission_without_account_access_is_denied`** (cross-account isolation, direct request).
  - **`test_list_endpoints_return_only_authorized_accounts`** (review AR-H1: `GET /notifications`, `/cached-notifications`,
    jobs listing, and the SSE surface are **row-filtered** to `user_account_access` — a global permission never returns
    another account's rows, not just the direct-`account_id` path).
  - **`test_per_account_enforced_on_each_surface`** (review AR-M2: parametrized across notifications, jobs, sessions, SSE).
  - `test_audit_actor_is_server_derived_never_client_supplied`.
  - **`test_executions_ignores_client_supplied_authorizer`** (review AR-M3: a client attempt to set `authorized_by` on the
    executions endpoint is ignored/rejected; the authorizer is always the authenticated session user).
  - `test_errors_are_typed_and_non_sensitive`; **`test_error_response_has_correlation_id_and_redacts_internal_detail`**
    (review AR-L3); `test_failed_workflow_is_not_reported_as_http_200_success`.
  - **`test_no_mode_field_exists`**; `test_executions_endpoint_requires_dry_run_verified_parent_same_account_workflow`;
    `test_executions_rejects_needs_review_or_identity_failed_parent`; `test_executions_requires_matching_hashes_and_unexpired_input`;
    `test_dry_runs_idempotency_key_dedupes_resubmit` (review AR-L5); `test_jobs_plan_permission_does_not_grant_jobs_execute`.
  - **`test_sse_uses_real_authorizer_and_revocation_drops_stream`** (correction #9): INC-17 provides the concrete
    `Authorizer` implementation for the SSE stream (from INC-15) and proves that revoking a user's `user_account_access`
    drops/rebuilds their live stream. INC-15's stub is replaced by this real, authenticated authorizer here.
- **Initial failing-test expectation:** fail (routers absent).
- **Mock/fixtures:** TestClient; temp DB; stub portal (no live host).
- **Implementation steps:** authz dependency → typed errors → routers → dry-runs/executions endpoints with all guards.
- **Acceptance criteria:** per-account isolation enforced; direct EXECUTE impossible; truthful errors/status.
- **Safe offline verification:** `python -m pytest tests/app/api -v`.
- **Safety gates:** contributes to **G4**.
- **Expected git-diff scope:** `app/api/*`, tests.
- **Rollback:** unmount the new API.
- **Risks/failure behavior:** authorization failures deny; execution guards fail closed.
- **Subincrement split (correction #7):**
  - **INC-17A** — `mcma/app/api/authz.py` (permission + per-account `user_account_access` checks, incl. list-row
    filtering) + `mcma/app/api/errors.py` (typed problem responses + correlation id + redaction) + server-derived audit;
    tests: per-account/list-filter/audit/typed-errors.
  - **INC-17B** — `mcma/app/api/*.py` routers, esp. `POST /jobs/dry-runs` and `POST /jobs/{id}/executions` with all
    guards, plus the concrete SSE `Authorizer` + revocation; tests: no-mode/executions-guards/idempotency/SSE-revocation.
- **Definition of Done:** authz + endpoint-guard tests green.
- **Approval boundary:** stop before INC-18.

---

## INC-18 — TLS-only LAN deployment + internal CA + certificate operations

- **Purpose/outcome:** Serve only over TLS; document the internal CA, root distribution to office machines, renewal with
  overlap, and **fail-to-serve on certificate failure** (no silent HTTP fallback).
- **Why here:** authenticated cookies require `Secure`; INV-11 requires no plaintext transport.
- **Prerequisites:** INC-17.
- **Addresses:** ADR-0008; API_CONTRACTS §1; INV-11.
- **Baseline files modified/retired:** the baseline `0.0.0.0:8000` plain-HTTP bind and `Autoriser_Reseau_Local.bat`
  `profile=any` rule are superseded; retirement of the old launchers is coordinated in INC-22.
- **Target modules/files introduced:** `app/serve.py` (TLS bootstrap; refuse to start without a valid cert/key),
  `deploy/tls/README.md` (internal CA, distribution via GPO/manual import, renewal runbook, failure handling),
  `deploy/serve.md` (single Windows service, one worker, single-instance mutex, configurable bind/subnet). Tests under
  `tests/app/serve/` (config-level: cert-missing → refuse to serve; no HTTP listener in production mode).
- **DB migration impact:** none.
- **Dependency/config impact:** TLS config from `mcma.core.config`; a **configurable** subnet allowlist (defense-in-depth,
  off by default; when set it filters but **never** disables auth).
- **Feature flags/adapters:** a documented dev-mode may use loopback TLS with a dev cert; production requires the internal CA cert.
- **Out-of-scope:** obtaining the actual office certificates (operational task in the runbook).
- **Tests-first:** `test_service_refuses_to_start_without_valid_cert`; `test_no_plain_http_listener_in_production_mode`
  (review AR-L4: the plan **intentionally** serves HTTPS-only and does **not** run even the optional HTTP→HTTPS redirect
  listener that `API_CONTRACTS.md` §1 permits — smaller attack surface; if a redirect is ever needed it is an external
  reverse proxy, not this service); `test_subnet_filter_absent_does_not_disable_auth`.
- **Initial failing-test expectation:** fail (serve bootstrap absent).
- **Mock/fixtures:** a temporary self-signed cert for the "valid cert" case.
- **Implementation steps:** TLS bootstrap + refuse-without-cert → production has no HTTP listener → subnet middleware (defense-in-depth) → runbook.
- **Acceptance criteria:** no plaintext transport; cert failure = no service; auth never bypassed by subnet config.
- **Safe offline verification:** `python -m pytest tests/app/serve -v`.
- **Safety gates:** **G4** (phase gate).
- **Expected git-diff scope:** `app/serve.py`, `deploy/*`, tests.
- **Rollback:** revert to the previous (loopback) serve mode; never to plain-HTTP LAN exposure.
- **Risks/failure behavior:** any TLS problem fails to serve (fail-closed), never falls back to HTTP.
- **Definition of Done:** TLS-only proven; **Gate 4 review** ready.
- **Approval boundary:** stop; **Gate 4 review** before Phase 6.
