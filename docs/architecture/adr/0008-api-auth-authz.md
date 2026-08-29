# ADR-0008 — API authentication/authorization; TLS; configurable LAN exposure

**Status:** Accepted (design). **Baseline:** `0290fe9…`.

## Context
The current API binds `0.0.0.0:8000` with no auth/CORS; any LAN host can drive the portal or spawn processes; the audit
actor comes from client-side data; a firewall rule opens the port on all profiles (`docs/recovery/KNOWN_FAILURES.md`
F18/F19/F20). INV-11 is violated.

## Decision
- **TLS required** for authenticated deployment: an internal CA issues the server cert; the CA root is distributed to
  office machines; certs are renewed with overlap; on cert failure the service **does not serve** — **auth never falls
  back to plain HTTP**. Any HTTP port only redirects to HTTPS.
- **Authentication** behind an **`AuthProvider`** seam (future Windows AD without touching domain/workflow). Initial
  `LocalUserAuthProvider`: local users, **Argon2id**, **no default credentials** (forced admin bootstrap). **Secure
  server-side sessions** (opaque cookie, `HttpOnly`/`SameSite=Strict`/`Secure`, idle+absolute expiry). **CSRF** on
  state-changing requests. **Audit actor = authenticated user** (server-derived).
- **Authorization** by a **Permission enum** (`notifications:read/update`, `jobs:plan`, `jobs:execute`, `jobs:view`,
  `sessions:manage`, `accounts:manage`, `users:manage`) mapped to configurable roles; **a viewer gets no mutation
  rights**; notification-view is separate from automation permission; **`jobs:plan` (dry-run) is separate from
  `jobs:execute`** (correction #3).
- **Direct EXECUTE is structurally impossible (correction #3):** no `mode` parameter exists. DRY_RUN is created at
  `POST /jobs/dry-runs`; EXECUTE only at `POST /jobs/{dry_run_job_id}/executions`, which derives `authorized_by_user_id`
  from the session, requires a `DRY_RUN_VERIFIED` parent of the same account+workflow, revalidates per-account authz,
  matches `input_hash`/`plan_hash`, requires unexpired retained input, rejects `NEEDS_REVIEW`/`IDENTITY_FAILED` parents,
  and creates an independent EXECUTE job (`API_CONTRACTS.md` §4).
- **Per-account authorization (correction #9):** permissions are scoped by `user_account_access`; every account-scoped
  endpoint (notifications, jobs, sessions, SSE) checks both the permission and account membership. A global `jobs:view`
  alone never exposes another account's dossiers.
- **Secure first-admin bootstrap (correction #9):** local-only (loopback/console), single-use, expiring; a LAN caller can
  never claim the first admin; disabled once an admin exists.
- **Account deletion:** deactivate/archive (`accounts.active=0`); never destroy records referenced by jobs/claims/audits.
- **Configurable LAN exposure:** host/port/allowed-subnet from typed config; the subnet filter is **defense-in-depth
  only** and **never disables authentication**; no hardcoded `192.168.1.0/24`.
- **Errors** are typed and non-sensitive (no raw `str(e)`); failures are reported truthfully (no 200-wrapping-failure).

## Consequences
- (+) INV-11 satisfied; least-privilege; trustworthy audit; safe LAN posture.
- (−) TLS/PKI operational setup and a user/role admin surface (runbook + admin endpoints).
