# API CONTRACTS

**Baseline:** `0290fe9…` · target design. Applies decisions #1 (TLS), #2 (auth), #6 (SSE), #8 (human finalization).
Fixes `SAFETY_INVARIANTS.md` INV-11. Not implemented yet.

---

## 1. Transport — TLS required (decision #1)
- **TLS is mandatory** for authenticated LAN deployment. The production design is **not** built around plain HTTP.
- **Internal CA:** an internal certificate authority issues the server certificate (SAN = the server hostname/LAN name).
- **Distribution:** the CA root certificate is distributed to office computers (e.g., via Group Policy / a documented
  manual import) so browsers trust the server without warnings.
- **Renewal:** certificates are renewed on a schedule with validity overlap; the runbook covers rotation without downtime.
- **Failure handling:** if the certificate/key is missing, unreadable, or invalid, the service **fails to start / does
  not serve** — **authentication never silently falls back to insecure HTTP.** A plain-HTTP listener is not provided in
  production; any HTTP port exists only to redirect to HTTPS.

## 2. Authentication (decision #2)
- **AuthProvider boundary** (`MODULE_BOUNDARIES.md` §3): domain/workflow code never references a concrete mechanism.
  Initial `LocalUserAuthProvider`; `WindowsAdAuthProvider` can be added later without touching domain/workflow code.
- **Local users**, **Argon2id** password hashing. **No default credentials** — first run requires an admin bootstrap
  that forces setting a password (footgun A2).
- **Secure first-admin bootstrap (correction #9):** bootstrap is **local-only** (bound to loopback / the console
  session), **single-use**, and **expiring** (a short-lived token generated into a service-account-readable local file or
  the console). A **LAN caller can never claim the first admin account** — the bootstrap endpoint rejects any non-loopback
  origin and is disabled permanently once the first admin exists.
- **Secure server-side sessions:** an opaque session id in a cookie (`HttpOnly`, `SameSite=Strict`, `Secure` — valid
  because TLS is required); session state server-side, with idle + absolute expiry and logout invalidation.
- **CSRF protection** on all state-changing requests (double-submit token or per-session token).
- **Audit actor is the authenticated user**, never a client-supplied name.

## 3. Authorization — permissions & roles (footgun A12)
Permission enum: `notifications:read`, `notifications:update`, `jobs:submit`, `jobs:view`, `sessions:manage`,
`accounts:manage`, `users:manage`. Default role→permission map (roles are configurable bundles):
| Role | Permissions |
|---|---|
| viewer | notifications:read, jobs:view |
| clerk | + notifications:update |
| operator | + jobs:submit |
| admin | + sessions:manage, accounts:manage, users:manage |
Each endpoint checks a specific permission server-side. **A viewer receives no mutation rights.**

**Per-account authorization (correction #9):** a permission grants nothing until it is **scoped to the accounts the user
may access** (`user_account_access`, `DATA_MODEL.md` §2). Every account-scoped endpoint — `notifications`, `jobs`,
`sessions`, and the SSE stream — enforces both the permission **and** membership in `user_account_access` for the target
`account_id`. **A global `jobs:view` (or `notifications:read`) alone must not expose another account's dossiers.** Listing
endpoints return only the accounts the caller may access; a request for an unauthorized `account_id` is denied (404/403).

**Account deletion (correction #9):** deletion normally **deactivates/archives** (`accounts.active=0`); records referenced
by `automation_jobs`, `claims`, `audit_events` are never destroyed.

## 4. Endpoints (typed pydantic request/response)
| Method | Path | Permission | Notes |
|---|---|---|---|
| POST | `/api/v1/auth/login` | — | issues session cookie + CSRF token |
| POST | `/api/v1/auth/logout` | authenticated | invalidates session |
| GET | `/api/v1/auth/me` | authenticated | current user + permissions |
| GET | `/api/v1/notifications` | notifications:read | live extraction (per-account, lease-governed) |
| GET | `/api/v1/cached-notifications` | notifications:read | from DB, no browser |
| POST | `/api/v1/notification-actions` | notifications:update | actor server-derived; optimistic version |
| GET/POST/DELETE | `/api/v1/accounts` | accounts:manage | account registry |
| POST | `/api/v1/sessions/login` | sessions:manage | triggers the desktop onboarding tool flow (decision #6) |
| GET | `/api/v1/sessions/status` | sessions:manage | session validity per account |
| POST | `/api/v1/jobs` | jobs:submit | async; body `{account_id, workflow, mode, input, idempotency_key}` → `job_id` |
| GET | `/api/v1/jobs/{id}` | jobs:view | job status, reason_code, readiness/diff report |
| GET | `/api/v1/events/stream` | notifications:read (+ per-account authz) | SSE (decision #6, §5) |
| GET | `/api/v1/health` | — | liveness only |
| GET | `/api/v1/ready` | — | real readiness (DB, migrations, session vault reachable) |

- **Async jobs:** `POST /jobs` enqueues; the runner executes under the per-account lease. There is **no** endpoint that
  performs a final portal save — the agent never invokes Enregistrer/Valider/Clôturer/GED (decision #8). A job's terminal
  automation result is `READY_FOR_HUMAN_REVIEW` with a readiness/diff report.
- **Configurable LAN exposure:** bind host/port + optional allowed-subnet from typed config. The subnet check is
  **defense-in-depth only**; an absent/empty/invalid subnet config **does not disable authentication** (footgun A10).

## 5. SSE (decision #6)
- `GET /api/v1/events/stream?account_id=…` — **one authorized stream per account** by default (a multiplexed,
  server-filtered stream is an option). Events use the **global `event_id`** as the SSE `id:`.
- **Reconnect:** the client sends `Last-Event-ID`; the server replays `event_id > cursor`, **authorization-filtered**.
  If the cursor is older than the earliest retained event, the server sends a **full-state snapshot** (forced resync)
  then resumes deltas.
- **Long-lived authz:** permissions are revalidated periodically; on revocation the stream is dropped/rebuilt.
- Retention is bounded by time/count, independent of any client cursor (`DATA_MODEL.md` §8).

## 6. Error handling
No raw `str(e)` to clients (fixes F19). Errors return typed, non-sensitive problem responses; internal detail goes to
redacted server logs with a correlation id. A failed/expired workflow is reported truthfully (never HTTP 200 "success"
wrapping a failure — fixes F20).
