-- Forward-only. Durable ownership/dispatch protocol between the central
-- server and paired Windows workstation runners (Phase 1C-A): claim
-- selection, lease renewal, and release/expiry. This table is added
-- SEPARATELY from automation_jobs -- runner-control fields are never
-- added directly to automation_jobs, and its own state-machine CHECK
-- constraints are never weakened to make room for dispatch concerns. No
-- Playwright/form-filling exists in this phase: this table only tracks
-- WHO currently owns the right to work a job, never portal state.
--
-- What is never stored here: the claim token itself (only its SHA-256
-- digest, exactly like runner_enrollments.code_digest / runners.
-- credential_digest in 0005), typed_input, or any portal/claimant data. A
-- row is inserted ONCE PER CLAIM ATTEMPT -- never reused/updated in place
-- across a re-claim -- and `generation` is a durable, monotonically
-- increasing PER-JOB counter (1, 2, 3, ... across that job's successive
-- assignment attempts). Renew/release match on claim_token_digest AND
-- generation AND runner_id together, so a stale claim token can never be
-- mistaken for authority over a newer assignment even in principle, on
-- top of the digest's own uniqueness.
--
-- At most one CLAIMED (active) assignment exists per job, and at most one
-- CLAIMED assignment exists per runner (first pilot: one job at a time per
-- workstation) -- both enforced by partial UNIQUE indexes below, not just
-- application logic. Finished (RELEASED/EXPIRED) rows are never deleted:
-- they are the durable, queryable audit trail for a job's assignment
-- history.

CREATE TABLE workstation_job_dispatch (
  assignment_id      TEXT PRIMARY KEY,
  job_id             TEXT NOT NULL REFERENCES automation_jobs(job_id),
  runner_id          TEXT NOT NULL REFERENCES runners(runner_id),
  generation         INTEGER NOT NULL CHECK (generation >= 1),
  claim_token_digest TEXT NOT NULL UNIQUE CHECK (length(claim_token_digest) = 64),
  status             TEXT NOT NULL CHECK (status IN ('CLAIMED', 'RELEASED', 'EXPIRED')),
  claimed_at         TEXT NOT NULL,
  lease_expires_at   TEXT NOT NULL,
  last_renewed_at    TEXT,
  finished_at        TEXT,
  -- Fixed, bounded outcome/error code -- NULL while CLAIMED, mandatory
  -- once finished, and constrained to the exact reason set each terminal
  -- status may ever record (never free text, never a client-chosen value).
  outcome_code       TEXT CHECK (outcome_code IS NULL OR outcome_code IN (
                        'CANCELLED_BEFORE_EXECUTION', 'RUNNER_SHUTDOWN', 'EXECUTION_NOT_AVAILABLE', 'LEASE_EXPIRED')),
  CHECK (lease_expires_at >= claimed_at),
  CHECK (last_renewed_at IS NULL OR last_renewed_at >= claimed_at),
  CHECK ((status = 'CLAIMED') = (finished_at IS NULL)),
  CHECK (status != 'CLAIMED' OR outcome_code IS NULL),
  -- `IS NOT NULL AND ... IN (...)` (not just `IN (...)`): SQLite's `IN`
  -- yields NULL, not false, when the left side is NULL, so `status !=
  -- 'RELEASED' OR outcome_code IN (...)` would silently PASS a RELEASED
  -- row with a NULL outcome_code (false OR NULL = NULL, and a NULL CHECK
  -- result is treated as satisfied). The explicit IS NOT NULL forces that
  -- case to evaluate to false instead.
  CHECK (status != 'RELEASED' OR (outcome_code IS NOT NULL
         AND outcome_code IN ('CANCELLED_BEFORE_EXECUTION', 'RUNNER_SHUTDOWN', 'EXECUTION_NOT_AVAILABLE'))),
  -- `IS` (not `=`): same NULL pitfall as above -- `outcome_code = 'LEASE_EXPIRED'`
  -- is NULL, not false, when outcome_code is NULL, but `IS` compares NULL
  -- as an ordinary value and correctly evaluates to false there.
  CHECK (status != 'EXPIRED' OR outcome_code IS 'LEASE_EXPIRED'));

-- At most one active (CLAIMED) assignment per job, and per runner (first
-- pilot: one job at a time per workstation) -- a database guarantee, not
-- just application logic.
CREATE UNIQUE INDEX uq_workstation_job_dispatch_active_job ON workstation_job_dispatch(job_id) WHERE status = 'CLAIMED';
CREATE UNIQUE INDEX uq_workstation_job_dispatch_active_runner ON workstation_job_dispatch(runner_id) WHERE status = 'CLAIMED';

-- Claim-selection support: "does this job already have an active
-- assignment" / "does this runner already have one" / "what generation is
-- this job on" are all looked up by job_id/runner_id across ALL history,
-- not just active rows.
CREATE INDEX idx_workstation_job_dispatch_job ON workstation_job_dispatch(job_id);
CREATE INDEX idx_workstation_job_dispatch_runner ON workstation_job_dispatch(runner_id);

-- Lease-expiry recovery support: scan only CLAIMED rows whose lease has
-- already passed, ordered/filtered by lease_expires_at.
CREATE INDEX idx_workstation_job_dispatch_lease_expiry ON workstation_job_dispatch(lease_expires_at) WHERE status = 'CLAIMED';
