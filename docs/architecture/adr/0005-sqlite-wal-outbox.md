# ADR-0005 — SQLite WAL + transactional outbox; at-rest protection

**Status:** Accepted (design). **Baseline:** `0290fe9…`.

## Context
State currently lives in flat `logs/*.json` (logs double as the database), with non-atomic rewrites, no audit, and
claimant PII in cleartext (`docs/recovery/KNOWN_FAILURES.md` F21/F26). SSE/persistence needs atomic state + events.

## Decision
Use **SQLite in WAL mode** (one application writer, `foreign_keys=ON`, `busy_timeout`), DB **outside any served
directory**. Every state change and its **`event_outbox`** row are written in **one transaction** (transactional
outbox). `event_outbox.event_id` is a **global monotonic** integer; per-account `account_state_version` lives in the
payload. **At-rest protection is required now**: BitLocker + strict NTFS ACLs + encrypted/access-controlled backups + no
PII in logs/outbox/screenshots/plan snapshots. If BitLocker + encrypted backups cannot be guaranteed, **SQLCipher (or
equivalent) becomes mandatory** before storing production PII. **Backups** use SQLite's online backup API / a
WAL-coordinated procedure — never a plain copy of a running DB. **Migrations** are compatibility-aware (expand/contract);
not all are reversible, so a tested backup/restore runbook is the safety net.

## Consequences
- (+) Atomic, auditable state; durable outbox for SSE; PII protected at rest.
- (−) Adds a schema + migration discipline; DPAPI/backup operational steps (ADR-0007, runbook).
