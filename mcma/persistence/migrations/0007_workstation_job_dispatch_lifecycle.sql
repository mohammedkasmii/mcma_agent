-- 0007_workstation_job_dispatch_lifecycle.sql -- Phase 1C-B: extends the
-- workstation dispatch lifecycle to represent RUNNING (browser work in
-- progress on the workstation) and two new terminal outcomes, SUCCEEDED
-- and FAILED, alongside the existing RELEASED/EXPIRED. Never edits 0006 --
-- this is the documented SQLite create-copy-drop-rename procedure (see
-- 0002's own comment) since a CHECK constraint cannot be altered in place.
-- mcma.persistence.db.run_migrations already turns PRAGMA foreign_keys OFF
-- for this migration's transaction and verifies PRAGMA foreign_key_check
-- is clean before allowing it to commit -- nothing extra is needed here.
--
-- New invariants on top of 0006's:
--  * CLAIMED and RUNNING are both "active" -- the partial unique indexes
--    now cover both, so "at most one active assignment per job" and "at
--    most one active assignment per runner" hold across the WHOLE active
--    lifecycle, not just the CLAIMED half of it.
--  * RELEASED is reachable only from CLAIMED, never from RUNNING -- that
--    is a TRANSITION rule (dispatch.release_job requires status='CLAIMED'),
--    which a CHECK constraint (seeing only one row at a time, never a
--    transition) cannot itself enforce; it is enforced in mcma.app.
--    runners.dispatch and proven by tests, not by this schema alone.
--  * SUCCEEDED/FAILED are new terminal statuses, each requiring its own
--    fixed outcome_code and a mandatory finished_at, exactly like
--    RELEASED/EXPIRED already do.
--  * Still never stores a claim token, typed input, portal content, a
--    credential, exception text, or free-form error text -- outcome_code
--    remains a fixed, closed enum, extended (not loosened) below.
--  * Every existing row (history) is preserved exactly.

CREATE TABLE workstation_job_dispatch_new (
  assignment_id      TEXT PRIMARY KEY,
  job_id             TEXT NOT NULL REFERENCES automation_jobs(job_id),
  runner_id          TEXT NOT NULL REFERENCES runners(runner_id),
  generation         INTEGER NOT NULL CHECK (generation >= 1),
  claim_token_digest TEXT NOT NULL UNIQUE CHECK (length(claim_token_digest) = 64),
  status             TEXT NOT NULL CHECK (status IN ('CLAIMED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'RELEASED', 'EXPIRED')),
  claimed_at         TEXT NOT NULL,
  lease_expires_at   TEXT NOT NULL,
  last_renewed_at    TEXT,
  started_at         TEXT,
  finished_at        TEXT,
  -- Fixed, bounded outcome/error code -- NULL while active (CLAIMED/
  -- RUNNING), mandatory once terminal, and constrained to the exact
  -- reason set each terminal status may ever record (never free text,
  -- never a client-chosen value).
  outcome_code       TEXT CHECK (outcome_code IS NULL OR outcome_code IN (
                        'CANCELLED_BEFORE_EXECUTION', 'RUNNER_SHUTDOWN', 'EXECUTION_NOT_AVAILABLE', 'LEASE_EXPIRED',
                        'IDENTITY_MATCHED', 'IDENTITY_NOT_MATCHED', 'SESSION_UNAVAILABLE', 'PORTAL_READ_FAILED',
                        'RUNNER_CANCELLED', 'NEEDS_REVIEW_NO_BROWSER', 'PLANNING_FAILED')),
  CHECK (lease_expires_at >= claimed_at),
  CHECK (last_renewed_at IS NULL OR last_renewed_at >= claimed_at),
  CHECK (started_at IS NULL OR started_at >= claimed_at),
  -- CLAIMED/RUNNING are the two active statuses -- both have no
  -- finished_at; every terminal status requires one.
  CHECK ((status IN ('CLAIMED', 'RUNNING')) = (finished_at IS NULL)),
  -- started_at is set exactly when (and only when) the assignment has
  -- ever reached RUNNING -- present for RUNNING itself and for every
  -- status a RUNNING assignment can terminate into (SUCCEEDED/FAILED/
  -- EXPIRED-while-RUNNING), absent for CLAIMED and for a CLAIMED
  -- assignment that ends in RELEASED/EXPIRED without ever starting.
  CHECK (status != 'CLAIMED' OR started_at IS NULL),
  CHECK (status != 'RUNNING' OR started_at IS NOT NULL),
  CHECK (status != 'CLAIMED' OR outcome_code IS NULL),
  CHECK (status != 'RUNNING' OR outcome_code IS NULL),
  -- `IS NOT NULL AND ... IN (...)` (not just `IN (...)`): SQLite's `IN`
  -- yields NULL, not false, when the left side is NULL, so a bare
  -- `status != 'X' OR outcome_code IN (...)` would silently PASS a
  -- terminal row with a NULL outcome_code (false OR NULL = NULL, and a
  -- NULL CHECK result is treated as satisfied) -- see 0006's own comment
  -- for the identical reasoning this repeats.
  CHECK (status != 'RELEASED' OR (outcome_code IS NOT NULL
         AND outcome_code IN ('CANCELLED_BEFORE_EXECUTION', 'RUNNER_SHUTDOWN', 'EXECUTION_NOT_AVAILABLE'))),
  CHECK (status != 'EXPIRED' OR outcome_code IS 'LEASE_EXPIRED'),
  CHECK (status != 'SUCCEEDED' OR (outcome_code IS NOT NULL
         AND outcome_code IN ('IDENTITY_MATCHED', 'NEEDS_REVIEW_NO_BROWSER'))),
  CHECK (status != 'FAILED' OR (outcome_code IS NOT NULL
         AND outcome_code IN ('IDENTITY_NOT_MATCHED', 'SESSION_UNAVAILABLE', 'PORTAL_READ_FAILED', 'RUNNER_CANCELLED',
                               'PLANNING_FAILED'))));

INSERT INTO workstation_job_dispatch_new (
  assignment_id, job_id, runner_id, generation, claim_token_digest, status,
  claimed_at, lease_expires_at, last_renewed_at, started_at, finished_at, outcome_code
)
SELECT
  assignment_id, job_id, runner_id, generation, claim_token_digest, status,
  claimed_at, lease_expires_at, last_renewed_at, NULL, finished_at, outcome_code
FROM workstation_job_dispatch;

DROP TABLE workstation_job_dispatch;

ALTER TABLE workstation_job_dispatch_new RENAME TO workstation_job_dispatch;

-- At most one active (CLAIMED or RUNNING) assignment per job, and per
-- runner (first pilot: one job at a time per workstation) -- a database
-- guarantee, not just application logic. Recreated because DROP TABLE
-- above dropped every index that existed on the old table.
CREATE UNIQUE INDEX uq_workstation_job_dispatch_active_job ON workstation_job_dispatch(job_id) WHERE status IN ('CLAIMED', 'RUNNING');
CREATE UNIQUE INDEX uq_workstation_job_dispatch_active_runner ON workstation_job_dispatch(runner_id) WHERE status IN ('CLAIMED', 'RUNNING');

CREATE INDEX idx_workstation_job_dispatch_job ON workstation_job_dispatch(job_id);
CREATE INDEX idx_workstation_job_dispatch_runner ON workstation_job_dispatch(runner_id);

-- Lease-expiry recovery support: scan only active (CLAIMED or RUNNING)
-- rows whose lease has already passed, ordered/filtered by lease_expires_at.
CREATE INDEX idx_workstation_job_dispatch_lease_expiry ON workstation_job_dispatch(lease_expires_at) WHERE status IN ('CLAIMED', 'RUNNING');
