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
- **Authorization** by a **Permission enum** (`notifications:read/update`, `jobs:submit/view`, `sessions:manage`,
  `accounts:manage`, `users:manage`) mapped to configurable roles; **a viewer gets no mutation rights**;
  notification-view is separate from automation permission.
- **Configurable LAN exposure:** host/port/allowed-subnet from typed config; the subnet filter is **defense-in-depth
  only** and **never disables authentication**; no hardcoded `192.168.1.0/24`.
- **Errors** are typed and non-sensitive (no raw `str(e)`); failures are reported truthfully (no 200-wrapping-failure).

## Consequences
- (+) INV-11 satisfied; least-privilege; trustworthy audit; safe LAN posture.
- (−) TLS/PKI operational setup and a user/role admin surface (runbook + admin endpoints).
