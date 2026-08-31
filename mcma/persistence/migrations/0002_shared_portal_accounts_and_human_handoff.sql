-- 0002_shared_portal_accounts_and_human_handoff.sql -- correction batch
-- (owner amendment): (1) prevents duplicate shared PortalAccount profiles
-- -- entity ('MCMA'/'MAMDA') x scope (e.g. 'OUJDA'/'NADOR') -- from ever
-- being created more than once (adding an employee later must reuse the
-- existing four rows, never create a fifth); (2) extends automation_jobs'
-- status CHECK with AWAITING_HUMAN_CONFIRMATION and HUMAN_CONFIRMED_COMPLETE
-- for the human browser-handoff state machine (WORKFLOW_STATE_MODEL.md
-- correction). scope itself is deliberately left as unconstrained TEXT --
-- the application layer (mcma.domain) owns the canonical Oujda/Nador
-- values; the database only guarantees no duplicate pairing, never a
-- closed enum of city names.
--
-- automation_jobs' CHECK constraint cannot be altered in place in SQLite,
-- so this migration uses the documented create-copy-drop-rename procedure
-- (mcma.persistence.db.run_migrations turns PRAGMA foreign_keys OFF for
-- this migration's transaction and verifies PRAGMA foreign_key_check is
-- clean before allowing it to commit). Every existing row, every other
-- table's foreign key into automation_jobs(job_id) (job_inputs), and the
-- UNIQUE(account_id, idempotency_key) constraint are preserved exactly.

-- (1) No duplicate shared PortalAccount profile -------------------------

CREATE UNIQUE INDEX ux_accounts_entity_scope ON accounts (entity, scope);

-- (2) automation_jobs: expand the status CHECK ---------------------------

CREATE TABLE automation_jobs_new (
  job_id TEXT PRIMARY KEY,
  account_id TEXT NOT NULL REFERENCES accounts(account_id),
  requested_by_user_id TEXT NOT NULL REFERENCES users(user_id),
  authorized_by_user_id TEXT REFERENCES users(user_id),
  parent_job_id TEXT REFERENCES automation_jobs_new(job_id),
  workflow_name TEXT NOT NULL,
  mode TEXT NOT NULL CHECK (mode IN ('DRY_RUN','EXECUTE')),
  status TEXT NOT NULL CHECK (status IN (
     'QUEUED','PLANNING','NEEDS_REVIEW','PLANNED',
     'READ_ONLY_IDENTITY_CHECK','DRY_RUN_VERIFIED','IDENTITY_FAILED',
     'ACQUIRING_ACCOUNT_LOCK','IDENTITY_VERIFYING','IDENTITY_VERIFIED',
     'WRITING','VERIFYING','WRITE_ABORTED','READY_FOR_HUMAN_REVIEW',
     'AWAITING_HUMAN_CONFIRMATION','HUMAN_CONFIRMED_COMPLETE',
     'INTERRUPTED_NEEDS_HUMAN_REVIEW','ABORTED_ON_RESTART','ERROR')),
  input_hash TEXT NOT NULL, plan_hash TEXT,
  plan_snapshot TEXT,
  idempotency_key TEXT NOT NULL,
  reason_code TEXT,
  created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT,
  state_version INTEGER NOT NULL,
  UNIQUE (account_id, idempotency_key));

INSERT INTO automation_jobs_new (
  job_id, account_id, requested_by_user_id, authorized_by_user_id, parent_job_id,
  workflow_name, mode, status, input_hash, plan_hash, plan_snapshot,
  idempotency_key, reason_code, created_at, started_at, finished_at, state_version
)
SELECT
  job_id, account_id, requested_by_user_id, authorized_by_user_id, parent_job_id,
  workflow_name, mode, status, input_hash, plan_hash, plan_snapshot,
  idempotency_key, reason_code, created_at, started_at, finished_at, state_version
FROM automation_jobs;

DROP TABLE automation_jobs;

ALTER TABLE automation_jobs_new RENAME TO automation_jobs;
