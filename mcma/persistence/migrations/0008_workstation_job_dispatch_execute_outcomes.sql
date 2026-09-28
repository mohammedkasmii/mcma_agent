-- 0008_workstation_job_dispatch_execute_outcomes.sql -- Phase 1C-C, Pass 1:
-- extends workstation_job_dispatch's outcome_code enum to cover the
-- EXECUTE lifecycle's own closed result set
-- (mcma.app.runners.dispatch.EXECUTE_FINISH_RESULTS), alongside the
-- existing DRY_RUN-only outcomes 0006/0007 already added. Never edits
-- 0006 or 0007 -- this is the same documented SQLite create-copy-drop-
-- rename procedure (see 0002's own comment) since a CHECK constraint
-- cannot be altered in place. mcma.persistence.db.run_migrations already
-- turns PRAGMA foreign_keys OFF for this migration's transaction and
-- verifies PRAGMA foreign_key_check is clean before allowing it to
-- commit -- nothing extra is needed here.
--
-- New invariants on top of 0007's:
--  * status enum is UNCHANGED (CLAIMED/RUNNING/SUCCEEDED/FAILED/RELEASED/
--    EXPIRED already cover the EXECUTE lifecycle too -- an EXECUTE
--    assignment is CLAIMED, then RUNNING while the workstation performs
--    its pre-write verification and (if it proceeds) the write itself,
--    then terminates SUCCEEDED/FAILED exactly like a DRY_RUN assignment
--    does, just with a different outcome_code vocabulary).
--  * outcome_code is EXTENDED (never loosened) with the EXECUTE-only
--    values: READY_FOR_HUMAN_REVIEW (a new SUCCEEDED outcome),
--    IDENTITY_FAILED, WRITE_ABORTED, SESSION_NOT_READY,
--    INPUT_OR_PLAN_MISMATCH, INTERNAL_EXECUTION_ERROR and LEASE_LOST (new
--    FAILED outcomes; LEASE_LOST added in-place here, this migration's
--    own uncommitted correction pass -- see mcma.app.runners.dispatch.
--    EXECUTE_FINISH_RESULTS's own comment on why it is distinct from
--    RUNNER_CANCELLED despite both landing on WRITE_ABORTED). RUNNER_
--    CANCELLED already exists (0007) and is reused as-is for an EXECUTE
--    assignment's own FAILED outcome too.
--  * Still never stores a claim token, typed input, portal content, a
--    credential, exception text, or free-form error text -- outcome_code
--    remains a fixed, closed enum.
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
  -- never a client-chosen value). Extended here with the EXECUTE
  -- lifecycle's own closed result set.
  outcome_code       TEXT CHECK (outcome_code IS NULL OR outcome_code IN (
                        'CANCELLED_BEFORE_EXECUTION', 'RUNNER_SHUTDOWN', 'EXECUTION_NOT_AVAILABLE', 'LEASE_EXPIRED',
                        'IDENTITY_MATCHED', 'IDENTITY_NOT_MATCHED', 'SESSION_UNAVAILABLE', 'PORTAL_READ_FAILED',
                        'RUNNER_CANCELLED', 'NEEDS_REVIEW_NO_BROWSER', 'PLANNING_FAILED',
                        'READY_FOR_HUMAN_REVIEW', 'IDENTITY_FAILED', 'WRITE_ABORTED',
                        'SESSION_NOT_READY', 'INPUT_OR_PLAN_MISMATCH', 'INTERNAL_EXECUTION_ERROR', 'LEASE_LOST')),
  CHECK (lease_expires_at >= claimed_at),
  CHECK (last_renewed_at IS NULL OR last_renewed_at >= claimed_at),
  CHECK (started_at IS NULL OR started_at >= claimed_at),
  CHECK ((status IN ('CLAIMED', 'RUNNING')) = (finished_at IS NULL)),
  CHECK (status != 'CLAIMED' OR started_at IS NULL),
  CHECK (status != 'RUNNING' OR started_at IS NOT NULL),
  CHECK (status != 'CLAIMED' OR outcome_code IS NULL),
  CHECK (status != 'RUNNING' OR outcome_code IS NULL),
  CHECK (status != 'RELEASED' OR (outcome_code IS NOT NULL
         AND outcome_code IN ('CANCELLED_BEFORE_EXECUTION', 'RUNNER_SHUTDOWN', 'EXECUTION_NOT_AVAILABLE'))),
  CHECK (status != 'EXPIRED' OR outcome_code IS 'LEASE_EXPIRED'),
  -- SUCCEEDED: DRY_RUN's own two success outcomes, plus EXECUTE's own
  -- (the terminal automation state READY_FOR_HUMAN_REVIEW).
  CHECK (status != 'SUCCEEDED' OR (outcome_code IS NOT NULL
         AND outcome_code IN ('IDENTITY_MATCHED', 'NEEDS_REVIEW_NO_BROWSER', 'READY_FOR_HUMAN_REVIEW'))),
  -- FAILED: DRY_RUN's own four failure outcomes (RUNNER_CANCELLED shared
  -- with EXECUTE below -- same meaning, same status, distinguished only
  -- by which job's dispatch row it is on), plus EXECUTE's own six.
  CHECK (status != 'FAILED' OR (outcome_code IS NOT NULL
         AND outcome_code IN ('IDENTITY_NOT_MATCHED', 'SESSION_UNAVAILABLE', 'PORTAL_READ_FAILED', 'RUNNER_CANCELLED',
                               'PLANNING_FAILED', 'IDENTITY_FAILED', 'WRITE_ABORTED', 'SESSION_NOT_READY',
                               'INPUT_OR_PLAN_MISMATCH', 'INTERNAL_EXECUTION_ERROR', 'LEASE_LOST'))));

INSERT INTO workstation_job_dispatch_new (
  assignment_id, job_id, runner_id, generation, claim_token_digest, status,
  claimed_at, lease_expires_at, last_renewed_at, started_at, finished_at, outcome_code
)
SELECT
  assignment_id, job_id, runner_id, generation, claim_token_digest, status,
  claimed_at, lease_expires_at, last_renewed_at, started_at, finished_at, outcome_code
FROM workstation_job_dispatch;

DROP TABLE workstation_job_dispatch;

ALTER TABLE workstation_job_dispatch_new RENAME TO workstation_job_dispatch;

CREATE UNIQUE INDEX uq_workstation_job_dispatch_active_job ON workstation_job_dispatch(job_id) WHERE status IN ('CLAIMED', 'RUNNING');
CREATE UNIQUE INDEX uq_workstation_job_dispatch_active_runner ON workstation_job_dispatch(runner_id) WHERE status IN ('CLAIMED', 'RUNNING');

CREATE INDEX idx_workstation_job_dispatch_job ON workstation_job_dispatch(job_id);
CREATE INDEX idx_workstation_job_dispatch_runner ON workstation_job_dispatch(runner_id);

CREATE INDEX idx_workstation_job_dispatch_lease_expiry ON workstation_job_dispatch(lease_expires_at) WHERE status IN ('CLAIMED', 'RUNNING');
