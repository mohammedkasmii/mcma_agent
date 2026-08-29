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
- **DPAPI model (explicit):** either (a) the onboarding tool and the service run under the **same dedicated Windows
  identity** using **DPAPI CurrentUser**, or (b) **DPAPI LocalMachine** + **strict NTFS ACLs** granting decrypt to the
  **service account only**. Chosen at deploy time; never ambiguous. Decryption or binding failure → **fail closed**.
- **Session lifecycle:** creation (onboarding tool), transfer (encrypted blob referenced by `storage_ref`), decryption
  (only `portal`, at open), **rotation/revocation**, **atomic replacement** (temp + `os.replace`), and **exclusion** from
  logs/Git(glob)/screenshots/backups.
- **Per-account leases:** `account_leases(account_id PK, owner_instance_id, owner_job_id, fencing_token, acquired_at,
  heartbeat_at, expires_at)`. The **fencing token is checked immediately before every portal write**; expired or replaced
  ownership aborts further writes. The lease is authoritative across processes (login tool vs service); `asyncio.Lock` is
  only an in-process fast path. Session refresh and notification polling obey the same lease rules.

## Consequences
- (+) Credentials protected; correct multi-account isolation; cross-process single-writer with fencing.
- (−) Operational care around DPAPI scope and the onboarding tool's Windows identity (documented in the deploy runbook).
