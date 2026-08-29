# DATA MODEL

**Baseline:** `0290fe9…` · target design (SQLite WAL). Applies decisions #1 (automation_jobs), #3 (at-rest
protection), #5 (account_leases), #6 (SSE retention), #10 (identity/staging/backup/migrations). Not implemented yet.

---

## 1. Engine settings
SQLite in **WAL** mode; `foreign_keys=ON`; `busy_timeout` set; **single application writer** (one Uvicorn worker).
The DB file lives **outside any served directory**. At-rest protection: §9.

## 2. Accounts, sessions, users, permissions
```sql
CREATE TABLE accounts (
  account_id TEXT PRIMARY KEY, label TEXT NOT NULL,
  entity TEXT NOT NULL CHECK (entity IN ('MAMDA','MCMA')),
  scope  TEXT NOT NULL,                       -- OUJDA | NADOR | ... (extensible, no hardcoded count)
  active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL);

CREATE TABLE portal_sessions (
  session_id TEXT PRIMARY KEY,
  account_id TEXT NOT NULL REFERENCES accounts(account_id),
  storage_ref TEXT NOT NULL,                  -- opaque; identity is account_id, NEVER the path
  status TEXT NOT NULL,                        -- ACTIVE | REVOKED | EXPIRED
  last_validated_at TEXT, opened_identity_fingerprint TEXT);

CREATE TABLE users (
  user_id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,                 -- Argon2id (decision #2); NO default credentials
  role TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1);

CREATE TABLE role_permissions (role TEXT NOT NULL, permission TEXT NOT NULL, PRIMARY KEY(role, permission));
-- permission values are the Permission enum (DOMAIN_MODEL §2); a viewer has no mutation permission.
```

## 3. Claims, presence, polls (decisions #8, #10)
```sql
CREATE TABLE claims (
  claim_pk TEXT PRIMARY KEY,
  account_id TEXT NOT NULL REFERENCES accounts(account_id),
  portal_claim_id TEXT NOT NULL,              -- idSinistre, REQUIRED before insertion (decision #10)
  reference TEXT, insured TEXT, police TEXT, matricule_norm TEXT,
  presence_status TEXT NOT NULL DEFAULT 'ACTIVE'
    CHECK (presence_status IN ('ACTIVE','MISSING_PENDING_CONFIRMATION','RESOLVED_ON_PORTAL')),
  consecutive_absence_count INTEGER NOT NULL DEFAULT 0,
  last_complete_poll_version INTEGER,
  first_seen_version INTEGER NOT NULL, last_seen_version INTEGER NOT NULL,
  UNIQUE (account_id, portal_claim_id));       -- stable identity = account_id + idSinistre, never category

CREATE TABLE categories (code_alerte TEXT PRIMARY KEY, label TEXT NOT NULL);
CREATE TABLE category_presence (
  claim_pk TEXT NOT NULL REFERENCES claims(claim_pk),
  category_code TEXT NOT NULL REFERENCES categories(code_alerte),
  present INTEGER NOT NULL, since_version INTEGER NOT NULL, last_seen_poll_run_id TEXT,
  PRIMARY KEY (claim_pk, category_code));

CREATE TABLE poll_runs (
  poll_run_id TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES accounts(account_id),
  started_at TEXT NOT NULL, completed_at TEXT,
  status TEXT NOT NULL CHECK (status IN ('COMPLETE','PARTIAL','FAILED')),
  session_valid INTEGER NOT NULL);

-- staging for notifications lacking idSinistre (decision #10) — NEVER inserted into claims
CREATE TABLE unmatched_notifications (
  staging_id TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES accounts(account_id),
  reference TEXT, raw_payload TEXT NOT NULL,    -- PII-bearing; access-controlled, excluded from logs
  seen_at TEXT NOT NULL, resolved INTEGER NOT NULL DEFAULT 0);
```
**Three-poll lifecycle (decision #8):** only a `poll_runs` row with `status='COMPLETE' AND session_valid=1` may change
presence. First absence in such a poll: ACTIVE→MISSING_PENDING_CONFIRMATION, `consecutive_absence_count=1`. Three
consecutive such absences → RESOLVED_ON_PORTAL. A PARTIAL/FAILED/invalid-session poll neither increments nor resets the
counter. Any present-observation in a complete poll → reset to ACTIVE, count=0.

## 4. Automation jobs (decision #1)
```sql
CREATE TABLE automation_jobs (
  job_id TEXT PRIMARY KEY,
  account_id TEXT NOT NULL REFERENCES accounts(account_id),
  requested_by_user_id TEXT NOT NULL REFERENCES users(user_id),
  authorized_by_user_id TEXT REFERENCES users(user_id),
  parent_job_id TEXT REFERENCES automation_jobs(job_id),
  workflow_name TEXT NOT NULL,
  mode TEXT NOT NULL CHECK (mode IN ('DRY_RUN','EXECUTE')),
  status TEXT NOT NULL,
  input_hash TEXT NOT NULL, plan_hash TEXT,
  plan_snapshot TEXT,                          -- safe/non-secret; access-controlled, no PII (footgun A9)
  idempotency_key TEXT NOT NULL,
  reason_code TEXT,
  created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT,
  state_version INTEGER NOT NULL,
  UNIQUE (account_id, idempotency_key));
```
Every job transition writes this row **and** an `event_outbox` row in **one transaction**. Crash recovery:
`WORKFLOW_STATE_MODEL.md` §7.

## 5. Account leases (decision #5 — exact schema)
```sql
CREATE TABLE account_leases (
  account_id       TEXT PRIMARY KEY REFERENCES accounts(account_id),  -- unique lease target
  owner_instance_id TEXT NOT NULL,
  owner_job_id     TEXT,
  fencing_token    TEXT NOT NULL,               -- checked before EVERY portal write
  acquired_at      TEXT NOT NULL,
  heartbeat_at     TEXT NOT NULL,
  expires_at       TEXT NOT NULL);
```
Acquire is atomic (INSERT, or UPDATE where `expires_at < now`). The writer validates `fencing_token` immediately before
each portal write; an expired or replaced ownership **aborts** further writes (`SAFETY_MODEL.md` §5). `heartbeat_at` is
renewed while held; expiry frees a dead holder. Authoritative across processes (login tool vs service).

## 6. Employee actions & audit (server-derived identity)
```sql
CREATE TABLE employee_actions (
  action_id TEXT PRIMARY KEY, claim_pk TEXT NOT NULL REFERENCES claims(claim_pk),
  status TEXT NOT NULL, note TEXT,
  actor_user_id TEXT NOT NULL REFERENCES users(user_id),   -- server-derived, replaces localStorage authority
  updated_at TEXT NOT NULL, version INTEGER NOT NULL);
CREATE TABLE audit_events (
  audit_id TEXT PRIMARY KEY, actor_user_id TEXT, account_id TEXT, job_id TEXT,
  action TEXT NOT NULL, before_hash TEXT, after_hash TEXT, created_at TEXT NOT NULL);
-- audit stores hashes/redactions only; NO secrets or PII payloads.
```

## 7. Event outbox + monotonic versions (decisions #6, #7-SSE)
```sql
CREATE TABLE account_state_version (account_id TEXT PRIMARY KEY REFERENCES accounts(account_id), version INTEGER NOT NULL);
CREATE TABLE event_outbox (
  event_id INTEGER PRIMARY KEY AUTOINCREMENT,   -- GLOBAL monotonic; used as SSE id / Last-Event-ID
  account_id TEXT NOT NULL, account_state_version INTEGER NOT NULL,   -- per-account version lives in the payload
  aggregate TEXT NOT NULL, type TEXT NOT NULL, payload_json TEXT NOT NULL,  -- no PII
  created_at TEXT NOT NULL, published_at TEXT);                  -- published_at = fan-out progress only, NOT per-client delivery
```
- Written in the **same transaction** as the state change it describes.
- SSE cursor = the global `event_id` (not the per-account version).

## 8. SSE retention & recovery (decision #6)
- **Bounded retention by time AND count** (configurable), **not** by the minimum live client cursor — a disconnected or
  idle client must never block cleanup.
- **Snapshot + delta recovery:** a client reconnecting with `Last-Event-ID = cursor` replays `event_id > cursor`
  (authorization-filtered). If `cursor` is **older than the earliest retained event**, the server forces a **full-state
  resynchronization** (snapshot) rather than a partial delta.
- **Authorization revalidation** on long-lived connections: permissions are re-checked periodically; on revocation the
  affected stream is dropped/rebuilt (footgun A13).
- Cleanup deletes events older than the configured time/count window.

## 9. At-rest protection (decision #3)
Required now. Initial acceptable protection:
- **BitLocker** enabled on the server volume;
- **strict NTFS ACLs** on the DB directory (service account only);
- **encrypted, access-controlled backups**;
- **DB never under a publicly served directory**;
- **no PII** in logs, `event_outbox.payload_json`, screenshots, or `automation_jobs.plan_snapshot`.
If BitLocker + encrypted backups cannot be guaranteed, **SQLCipher (or equivalent DB encryption) becomes mandatory**
before storing production PII.

## 10. Backup & migrations (decision #10)
- **Backups** use SQLite's **online backup API** (`Connection.backup`) or a correctly WAL-coordinated procedure —
  **never** a plain file copy of a running DB. Backups are encrypted and access-controlled.
- **Migrations** are **compatibility-aware** (expand/contract). Forward migrations are tested; we do **not** promise
  every migration is reversible. Safety net = tested **backup/restore** runbook (`TEST_STRATEGY.md`).
```sql
CREATE TABLE schema_migrations (version TEXT PRIMARY KEY, applied_at TEXT NOT NULL);
```
