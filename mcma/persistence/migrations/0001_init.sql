-- 0001_init.sql -- INC-10: the complete initial schema, all 20 DATA_MODEL.md
-- tables (§2-§10), verbatim to that document. Forward-only; expand/contract
-- discipline applies to every later migration (never modify this file after
-- it has shipped).

-- §2: accounts, sessions, users, permissions ------------------------------

CREATE TABLE accounts (
  account_id TEXT PRIMARY KEY, label TEXT NOT NULL,
  entity TEXT NOT NULL CHECK (entity IN ('MAMDA','MCMA')),
  scope  TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL);

CREATE TABLE portal_sessions (
  session_id TEXT PRIMARY KEY,
  account_id TEXT NOT NULL REFERENCES accounts(account_id),
  storage_ref TEXT NOT NULL,
  status TEXT NOT NULL,
  last_validated_at TEXT, opened_identity_fingerprint TEXT);

CREATE TABLE users (
  user_id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1);

CREATE TABLE role_permissions (role TEXT NOT NULL, permission TEXT NOT NULL, PRIMARY KEY(role, permission));

CREATE TABLE user_account_access (
  user_id    TEXT NOT NULL REFERENCES users(user_id),
  account_id TEXT NOT NULL REFERENCES accounts(account_id),
  granted_at TEXT NOT NULL,
  PRIMARY KEY (user_id, account_id));

-- §3: claims, presence, polls ----------------------------------------------

CREATE TABLE claims (
  claim_pk TEXT PRIMARY KEY,
  account_id TEXT NOT NULL REFERENCES accounts(account_id),
  portal_claim_id TEXT NOT NULL,
  reference TEXT, insured TEXT, police TEXT, matricule_norm TEXT,
  first_seen_version INTEGER NOT NULL, last_seen_version INTEGER NOT NULL,
  UNIQUE (account_id, portal_claim_id),
  UNIQUE (account_id, claim_pk));

CREATE TABLE categories (code_alerte TEXT PRIMARY KEY, label TEXT NOT NULL);

CREATE TABLE category_presence (
  account_id     TEXT NOT NULL,
  claim_pk       TEXT NOT NULL,
  category_code  TEXT NOT NULL REFERENCES categories(code_alerte),
  present        INTEGER NOT NULL,
  presence_status TEXT NOT NULL DEFAULT 'ACTIVE'
    CHECK (presence_status IN ('ACTIVE','MISSING_PENDING_CONFIRMATION','RESOLVED_ON_PORTAL')),
  consecutive_absence_count INTEGER NOT NULL DEFAULT 0,
  last_complete_poll_version INTEGER,
  since_version  INTEGER NOT NULL,
  last_seen_poll_run_id TEXT,
  PRIMARY KEY (account_id, claim_pk, category_code),
  FOREIGN KEY (account_id, claim_pk) REFERENCES claims(account_id, claim_pk));

CREATE TABLE poll_runs (
  poll_run_id TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES accounts(account_id),
  started_at TEXT NOT NULL, completed_at TEXT,
  status TEXT NOT NULL CHECK (status IN ('COMPLETE','PARTIAL','FAILED')),
  session_valid INTEGER NOT NULL);

CREATE TABLE poll_run_categories (
  poll_run_id   TEXT NOT NULL REFERENCES poll_runs(poll_run_id),
  category_code TEXT NOT NULL REFERENCES categories(code_alerte),
  status        TEXT NOT NULL CHECK (status IN ('COMPLETE','PARTIAL','FAILED')),
  session_valid INTEGER NOT NULL,
  completed_at  TEXT,
  rows_seen     INTEGER,
  PRIMARY KEY (poll_run_id, category_code));

CREATE TABLE unmatched_notifications (
  staging_id TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES accounts(account_id),
  reference TEXT, raw_payload TEXT NOT NULL,
  seen_at TEXT NOT NULL, resolved INTEGER NOT NULL DEFAULT 0);

CREATE TABLE observed_finalizations (
  claim_pk        TEXT NOT NULL REFERENCES claims(claim_pk),
  observed_at     TEXT NOT NULL,
  evidence_source TEXT NOT NULL,
  poll_run_id     TEXT REFERENCES poll_runs(poll_run_id),
  PRIMARY KEY (claim_pk, observed_at));

-- §4/§4a: automation jobs + durable job input --------------------------

CREATE TABLE automation_jobs (
  job_id TEXT PRIMARY KEY,
  account_id TEXT NOT NULL REFERENCES accounts(account_id),
  requested_by_user_id TEXT NOT NULL REFERENCES users(user_id),
  authorized_by_user_id TEXT REFERENCES users(user_id),
  parent_job_id TEXT REFERENCES automation_jobs(job_id),
  workflow_name TEXT NOT NULL,
  mode TEXT NOT NULL CHECK (mode IN ('DRY_RUN','EXECUTE')),
  status TEXT NOT NULL CHECK (status IN (
     'QUEUED','PLANNING','NEEDS_REVIEW','PLANNED',
     'READ_ONLY_IDENTITY_CHECK','DRY_RUN_VERIFIED','IDENTITY_FAILED',
     'ACQUIRING_ACCOUNT_LOCK','IDENTITY_VERIFYING','IDENTITY_VERIFIED',
     'WRITING','VERIFYING','WRITE_ABORTED','READY_FOR_HUMAN_REVIEW',
     'INTERRUPTED_NEEDS_HUMAN_REVIEW','ABORTED_ON_RESTART','ERROR')),
  input_hash TEXT NOT NULL, plan_hash TEXT,
  plan_snapshot TEXT,
  idempotency_key TEXT NOT NULL,
  reason_code TEXT,
  created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT,
  state_version INTEGER NOT NULL,
  UNIQUE (account_id, idempotency_key));

CREATE TABLE job_inputs (
  job_id           TEXT PRIMARY KEY REFERENCES automation_jobs(job_id),
  content_hash     TEXT NOT NULL,
  ciphertext       BLOB NOT NULL,
  pii_class        TEXT NOT NULL,
  created_at       TEXT NOT NULL,
  expires_at       TEXT NOT NULL,
  deleted_at       TEXT);

-- §5: account leases ---------------------------------------------------

CREATE TABLE account_leases (
  account_id       TEXT PRIMARY KEY REFERENCES accounts(account_id),
  owner_instance_id TEXT NOT NULL,
  owner_job_id     TEXT,
  fencing_token    TEXT NOT NULL,
  acquired_at      TEXT NOT NULL,
  heartbeat_at     TEXT NOT NULL,
  expires_at       TEXT NOT NULL);

-- §6: employee actions & audit ------------------------------------------

CREATE TABLE employee_actions (
  action_id TEXT PRIMARY KEY, claim_pk TEXT NOT NULL REFERENCES claims(claim_pk),
  status TEXT NOT NULL, note TEXT,
  actor_user_id TEXT NOT NULL REFERENCES users(user_id),
  updated_at TEXT NOT NULL, version INTEGER NOT NULL);

CREATE TABLE audit_events (
  audit_id TEXT PRIMARY KEY, actor_user_id TEXT, account_id TEXT, job_id TEXT,
  action TEXT NOT NULL, before_hash TEXT, after_hash TEXT, created_at TEXT NOT NULL);

-- §7: event outbox + monotonic versions ----------------------------------

CREATE TABLE account_state_version (account_id TEXT PRIMARY KEY REFERENCES accounts(account_id), version INTEGER NOT NULL);

CREATE TABLE event_outbox (
  event_id INTEGER PRIMARY KEY AUTOINCREMENT,
  account_id TEXT NOT NULL, account_state_version INTEGER NOT NULL,
  aggregate TEXT NOT NULL, type TEXT NOT NULL, payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL, published_at TEXT);

-- §10: migrations ---------------------------------------------------------

CREATE TABLE schema_migrations (version TEXT PRIMARY KEY, applied_at TEXT NOT NULL);
