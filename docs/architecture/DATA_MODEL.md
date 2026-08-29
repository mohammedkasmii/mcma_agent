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

-- Per-account authorization (correction #9): a permission grants nothing until scoped to the accounts
-- the user may see/act on. Enforced for notifications, jobs, sessions and SSE.
CREATE TABLE user_account_access (
  user_id    TEXT NOT NULL REFERENCES users(user_id),
  account_id TEXT NOT NULL REFERENCES accounts(account_id),
  granted_at TEXT NOT NULL,
  PRIMARY KEY (user_id, account_id));
```
**Account lifecycle (correction #9):** account "deletion" normally **deactivates/archives** (`accounts.active=0`); records
referenced by `automation_jobs`, `claims`, `audit_events` are **never destroyed**. Hard deletion is an admin-only,
out-of-band operation guarded against referential loss.

## 3. Claims, presence, polls (decisions #8, #10; **correction #1: presence is category-scoped**)
The claim is pure identity — it carries **no** presence lifecycle. The lifecycle lives on `category_presence`,
**independently per `(account_id, claim_pk, category_code)`**.
```sql
CREATE TABLE claims (
  claim_pk TEXT PRIMARY KEY,
  account_id TEXT NOT NULL REFERENCES accounts(account_id),
  portal_claim_id TEXT NOT NULL,              -- idSinistre, REQUIRED before insertion (decision #10)
  reference TEXT, insured TEXT, police TEXT, matricule_norm TEXT,
  first_seen_version INTEGER NOT NULL, last_seen_version INTEGER NOT NULL,
  UNIQUE (account_id, portal_claim_id),        -- stable identity = account_id + idSinistre, never category
  UNIQUE (account_id, claim_pk));               -- composite target for cross-account integrity (correction #4)
  -- NOTE: presence_status / consecutive_absence_count / last_complete_poll_version were MOVED to category_presence.

CREATE TABLE categories (code_alerte TEXT PRIMARY KEY, label TEXT NOT NULL);

-- Per-category lifecycle: one row per (account_id, claim_pk, category_code).
-- Correction #4: a SINGLE composite FK ties account_id+claim_pk to ONE claim row — no two independent FKs that could
-- pair an account with another account's claim.
CREATE TABLE category_presence (
  account_id     TEXT NOT NULL,
  claim_pk       TEXT NOT NULL,
  category_code  TEXT NOT NULL REFERENCES categories(code_alerte),
  present        INTEGER NOT NULL,
  presence_status TEXT NOT NULL DEFAULT 'ACTIVE'
    CHECK (presence_status IN ('ACTIVE','MISSING_PENDING_CONFIRMATION','RESOLVED_ON_PORTAL')),
  consecutive_absence_count INTEGER NOT NULL DEFAULT 0,
  last_complete_poll_version INTEGER,          -- version of the last COMPLETE, valid-session poll of THIS category
  since_version  INTEGER NOT NULL,
  last_seen_poll_run_id TEXT,
  PRIMARY KEY (account_id, claim_pk, category_code),
  FOREIGN KEY (account_id, claim_pk) REFERENCES claims(account_id, claim_pk));  -- correction #4: one pair, one claim

CREATE TABLE poll_runs (
  poll_run_id TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES accounts(account_id),
  started_at TEXT NOT NULL, completed_at TEXT,
  status TEXT NOT NULL CHECK (status IN ('COMPLETE','PARTIAL','FAILED')),
  session_valid INTEGER NOT NULL);             -- run-level session validity

-- Per-category completeness of a poll run (correction #1): a poll can complete some categories and fail others
CREATE TABLE poll_run_categories (
  poll_run_id   TEXT NOT NULL REFERENCES poll_runs(poll_run_id),
  category_code TEXT NOT NULL REFERENCES categories(code_alerte),
  status        TEXT NOT NULL CHECK (status IN ('COMPLETE','PARTIAL','FAILED')),
  session_valid INTEGER NOT NULL,              -- session validity observed for THIS category fetch
  completed_at  TEXT,
  rows_seen     INTEGER,                        -- completeness evidence (full-dataset fetch succeeded)
  PRIMARY KEY (poll_run_id, category_code));

-- staging for notifications lacking idSinistre (decision #10) — NEVER inserted into claims
CREATE TABLE unmatched_notifications (
  staging_id TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES accounts(account_id),
  reference TEXT, raw_payload TEXT NOT NULL,    -- PII-bearing; access-controlled, excluded from logs
  seen_at TEXT NOT NULL, resolved INTEGER NOT NULL DEFAULT 0);
```
**Three-poll lifecycle — per category (decision #8, correction #1):** a presence transition for
`(account_id, claim_pk, category_code)` may occur **only** when **that exact category** has a
`poll_run_categories` row with `status='COMPLETE' AND session_valid=1`. First absence under such a completed category:
ACTIVE→MISSING_PENDING_CONFIRMATION, `consecutive_absence_count=1`. **Three consecutive** complete, valid-session
absences **of that category** → RESOLVED_ON_PORTAL (for that category only). A **PARTIAL/FAILED/invalid** fetch of a
category neither increments nor resets its counter, **and never affects another category**. Any present-observation of
the category in a complete poll → reset that category to ACTIVE, count=0.

**Observed human finalization (correction #2):** `FINALIZED_BY_HUMAN` is NOT an automation-job status. It is an observed
claim/business event with its own evidence source and timestamp:
```sql
CREATE TABLE observed_finalizations (
  claim_pk        TEXT NOT NULL REFERENCES claims(claim_pk),
  observed_at     TEXT NOT NULL,
  evidence_source TEXT NOT NULL,               -- e.g. POLL_READBACK | PORTAL_STATUS_SCRAPE
  poll_run_id     TEXT REFERENCES poll_runs(poll_run_id),
  PRIMARY KEY (claim_pk, observed_at));
```
It records that a human completed the final save in the portal; it never mutates `automation_jobs` into a
human-completed automation status.

## 4. Automation jobs (decision #1)
```sql
CREATE TABLE automation_jobs (
  job_id TEXT PRIMARY KEY,
  account_id TEXT NOT NULL REFERENCES accounts(account_id),
  requested_by_user_id TEXT NOT NULL REFERENCES users(user_id),
  authorized_by_user_id TEXT REFERENCES users(user_id),
  parent_job_id TEXT REFERENCES automation_jobs(job_id),
  workflow_name TEXT NOT NULL,
  mode TEXT NOT NULL CHECK (mode IN ('DRY_RUN','EXECUTE')),  -- SET BY THE ENDPOINT, never a client field (correction #3)
  status TEXT NOT NULL CHECK (status IN (                    -- valid-status contract (correction #5)
     'QUEUED','PLANNING','NEEDS_REVIEW','PLANNED',
     'READ_ONLY_IDENTITY_CHECK','DRY_RUN_VERIFIED','IDENTITY_FAILED',
     'ACQUIRING_ACCOUNT_LOCK','IDENTITY_VERIFYING','IDENTITY_VERIFIED',
     'WRITING','VERIFYING','WRITE_ABORTED','READY_FOR_HUMAN_REVIEW',
     'INTERRUPTED_NEEDS_HUMAN_REVIEW','ABORTED_ON_RESTART','ERROR')),
  input_hash TEXT NOT NULL, plan_hash TEXT,
  plan_snapshot TEXT,                          -- safe/non-secret; access-controlled, no PII (footgun A9)
  idempotency_key TEXT NOT NULL,
  reason_code TEXT,                            -- e.g. INPUT_CHANGED, INVALID_TAX_ALLOCATION, AMBIGUOUS_GLASS, ...
  created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT,
  state_version INTEGER NOT NULL,
  UNIQUE (account_id, idempotency_key));
```
`mode` is chosen by the endpoint (`/jobs/dry-runs` → DRY_RUN, `/jobs/{id}/executions` → EXECUTE), never accepted from the
client (correction #3). Every job **transition** writes this row **and** an `event_outbox` row in **one transaction**.

**Durable enqueue (correction #5):** job **creation** is a single atomic transaction that writes **all** of:
`automation_jobs` (status `QUEUED`) + encrypted `job_inputs` (§4a) + an `account_state_version` bump + an `event_outbox`
event. If any part fails, **none** is committed (no half-created job, no input-less job). `QUEUED` is durable queued work
picked up by the runner. Crash recovery: `WORKFLOW_STATE_MODEL.md` §7.

**Repository/application invariants (corrections #3/#4):**
- `parent_job_id` (EXECUTE → DRY_RUN) must reference a DRY_RUN in `DRY_RUN_VERIFIED` state **of the same `account_id`
  and `workflow_name`**; enforced by a repository check (SQLite FKs cannot express "same account+workflow"), with tests.
- Cross-account integrity for `category_presence` is enforced by the composite FK above; a repository test proves that
  inserting a presence row pairing an `account_id` with another account's `claim_pk` **fails** (`TEST_STRATEGY.md`).

### 4a. Durable job input (correction #4 — a hash alone cannot execute or recover a job)
`automation_jobs.input_hash` is an integrity check, **not** the input. The actual typed input is retained encrypted so
an async job can execute and survive a restart:
```sql
CREATE TABLE job_inputs (
  job_id           TEXT PRIMARY KEY REFERENCES automation_jobs(job_id),  -- ownership: one input per job
  content_hash     TEXT NOT NULL,               -- sha256 of the canonical typed input == automation_jobs.input_hash
  ciphertext       BLOB NOT NULL,               -- DPAPI LocalMachine-encrypted (service-account ACL); never plaintext on disk
  pii_class        TEXT NOT NULL,               -- e.g. CONTAINS_PII (claimant data) — governs retention/redaction
  created_at       TEXT NOT NULL,
  expires_at       TEXT NOT NULL,               -- retention window; a cleanup job deletes past expiry
  deleted_at       TEXT);                        -- soft-delete marker for audit of removal
```
- **Encryption/access control:** encrypted with the same DPAPI LocalMachine + service-account-only ACL model as the
  session vault (`SAFETY_MODEL.md` §7); decrypt is service-only. Not logged; excluded from ordinary backups unless the
  backup itself is encrypted+access-controlled.
- **Retention/deletion:** kept until `expires_at`, then deleted; a completed/terminal job's input may be purged earlier
  per policy. `pii_class` drives handling.
- **Crash recovery:** on restart, a resumable job re-reads its `job_inputs` row; the runner recomputes `content_hash`
  and asserts it equals `automation_jobs.input_hash` before proceeding. If the input is missing, expired, undecryptable,
  or hash-mismatched, the job **fails closed to `ERROR`** with the exact reason code — `MISSING_JOB_INPUT`,
  `INPUT_EXPIRED`, `INPUT_UNDECRYPTABLE`, or `INPUT_HASH_MISMATCH` respectively (`WORKFLOW_STATE_MODEL.md` §7) — and is
  **never** executed on a guessed input.
- **EXECUTE exact-input rule:** an EXECUTE job references its approved DRY_RUN (`parent_job_id`) and executes **only** if
  the retained input's `content_hash` and the recomputed `plan_hash` match the approved snapshot; any mismatch →
  fail closed `INPUT_CHANGED`.
- **Expected mission identity (correction #4):** the typed input's expected identity MUST include the supplied insurer
  reference and/or `idSinistre` **plus a mandatory normalized registration plate**. A plan/job whose input lacks a
  registration plate is non-executable (fail closed) — see `DOMAIN_MODEL.md` §6 and `SAFETY_MODEL.md` §4.

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
Acquire is atomic (INSERT, or UPDATE where `expires_at < now`). The lease coordinates account access across processes
(login tool vs service) and prevents two holders from working the same account; `heartbeat_at` is renewed while held and
expiry frees a dead holder.

**Fencing caveat (correction #5 — do not overstate):** the fencing token is an **internal** guard. **SinAuto does not
validate any fencing token**, so the DB fence cannot make the *portal* reject a stale write; it only lets our own code
detect lease loss and stop. The real single-writer guarantee is therefore: **an OS single-instance mutex** ensuring only
one service process runs, and **only that single service process may hold row-write capability**. `owner_instance_id`
records which process holds the lease; on heartbeat loss the holder aborts (`SAFETY_MODEL.md` §5). The interactive login
tool never obtains row-write capability.

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
