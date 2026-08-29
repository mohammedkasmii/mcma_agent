# ADR-0007 — Multi-account session vault; leases; DPAPI

**Status:** Accepted (design). **Baseline:** `0290fe9…`.

## Context
Today there is one plaintext `mcma_auth_state.json`; identity is implied by a filename; there is no account concept, no
locking, and no protection of the session credential (`docs/recovery/KNOWN_FAILURES.md` F21/F23). Oujda/Nador are account
profiles in one office, not deployments.

## Decision
- **Registry-owned identity:** the `accounts` table is the source of account identity; `portal_sessions.storage_ref` is
  **opaque** — a filename/path never implies identity. Support any number of accounts (no hardcoded count).
- **Session→account binding & validation:** on open, `portal` compares scraped portal identity evidence to the account
  record; **write-capable jobs fail closed if identity cannot be positively verified** ("where evidence permits" is only
  acceptable for read/notification context).
- **DPAPI model (single, correction #6):** **DPAPI LocalMachine + service-account-only NTFS ACL** — no CurrentUser
  alternative. The **onboarding tool never writes the vault directory and never writes plaintext session state to disk**;
  it performs an **authenticated, single-use, account-bound local handoff** to the service, which validates the
  account/session evidence, encrypts (LocalMachine) and **atomically** stores it. Decryption or account-binding failure
  → **fail closed**.
- **Session lifecycle:** creation (onboarding tool, **in-memory only**) → authenticated single-use account-bound handoff
  → validate+encrypt+store (**service**, after **acquiring the account lease** so onboarding can't overwrite a session in
  use — correction #6) → decryption (only `portal`, at open) → **rotation/revocation** → **atomic replacement** (temp +
  `os.replace`) → **exclusion** from logs/Git(glob)/screenshots/backups. `POST /sessions/login` issues a one-time local
  onboarding token; the service never launches a visible desktop browser.
- **Per-account leases:** `account_leases(account_id PK, owner_instance_id, owner_job_id, fencing_token, acquired_at,
  heartbeat_at, expires_at)`. `execution` acquires the lease via `persistence` and passes a `LeaseHandle` to `portal`
  (which never reacquires it or imports sqlite). **Fencing caveat (correction #5):** SinAuto does not validate any fencing
  token, so the DB fence is an internal guard only; the authoritative single-writer guarantee is an **OS single-instance
  mutex** — only one service process runs and only it may hold row-write capability. On heartbeat loss the writer aborts
  routing and closes the write context. Session refresh and notification polling obey the same lease rules.

## Consequences
- (+) Credentials protected; correct multi-account isolation.
- **Single-writer guarantee (correction #7):** the authoritative guarantee is an **OS single-instance mutex plus exactly
  one write-capable service process** — **not** database fencing. SinAuto does not validate any fencing token, so the DB
  lease is **coordination and loss detection** only (it lets our own code detect that it no longer owns the account and
  stop), never true external fencing.
- (−) Operational care around DPAPI LocalMachine scope, the service account's NTFS ACL, and the single-instance mutex
  (documented in the deploy runbook).
