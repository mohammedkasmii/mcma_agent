-- 0009_notification_onboarding.sql -- forward-only. Durable, short-lived
-- onboarding requests that let an employee's Windows workstation runner
-- capture a SERVER-OWNED notification session (one of the four canonical
-- accounts, MCMA and MAMDA) through a visible browser on the employee's
-- desktop, then hand it ONCE to the central server over verified HTTPS.
--
-- The central server stays headless: this table is only the control plane
-- (who may open a login window, for which account, on which runner, until
-- when). The session material itself goes straight into the existing AES
-- server vault and is NEVER stored here.
--
-- State machine (closed; every transition is made by a conditional UPDATE
-- in mcma.app.runners.notification_onboarding):
--   PENDING   -> CLAIMED | CANCELLED | EXPIRED | FAILED
--   CLAIMED   -> SUCCEEDED | FAILED | CANCELLED | EXPIRED
--   SUCCEEDED, FAILED, CANCELLED, EXPIRED are terminal and permanent.
--
-- What is never stored: storage_state, cookies, credentials, OTP, a runner
-- bearer secret, the raw claim token (only its SHA-256 digest, like
-- workstation_job_dispatch.claim_token_digest in 0006), or any portal text.
-- All timestamps are SERVER clock values written by the service.
--
-- Fencing: `generation` is a per-account monotonic counter; renew/complete/
-- fail match on claim_token_digest AND generation AND runner_id, so an
-- expired or superseded request can never modify a newer one. Terminal rows
-- are never deleted (they are the audit trail). A SUCCEEDED row keeps its
-- digest so a completion retried after a lost response is answered
-- idempotently without storing anything twice.

CREATE TABLE notification_onboarding_requests (
  request_id          TEXT PRIMARY KEY CHECK (length(request_id) = 32),
  account_id          TEXT NOT NULL REFERENCES accounts(account_id)
                      CHECK (account_id IN ('acct-mcma-oujda', 'acct-mcma-nador', 'acct-mamda-oujda', 'acct-mamda-nador')),
  user_id             TEXT NOT NULL REFERENCES users(user_id),
  runner_id           TEXT NOT NULL REFERENCES runners(runner_id),
  generation          INTEGER NOT NULL CHECK (generation >= 1),
  status              TEXT NOT NULL CHECK (status IN ('PENDING', 'CLAIMED', 'SUCCEEDED', 'FAILED', 'CANCELLED', 'EXPIRED')),
  -- Runner-reported progress while CLAIMED (fixed enum, never free text).
  phase               TEXT CHECK (phase IS NULL OR phase IN ('OPENING_WINDOW', 'WINDOW_OPENED', 'WAITING_FOR_LOGIN')),
  claim_token_digest  TEXT UNIQUE CHECK (claim_token_digest IS NULL OR length(claim_token_digest) = 64),
  created_at          TEXT NOT NULL,
  expires_at          TEXT NOT NULL,     -- hard deadline for the whole request
  claimed_at          TEXT,
  lease_expires_at    TEXT,
  last_renewed_at     TEXT,
  cancel_requested_at TEXT,
  updated_at          TEXT NOT NULL,
  finished_at         TEXT,
  outcome_code        TEXT CHECK (outcome_code IS NULL OR outcome_code IN (
                         'SESSION_STORED',
                         'LOGIN_TIMED_OUT', 'LOGIN_WINDOW_CLOSED', 'LOGIN_PAGE_UNREACHABLE', 'UPLOAD_FAILED',
                         'RUNNER_BUSY', 'ACCESS_REVOKED', 'INTERNAL_ERROR',
                         'CANCELLED_BY_USER', 'RUNNER_SHUTDOWN',
                         'REQUEST_EXPIRED', 'LEASE_EXPIRED')),
  UNIQUE (account_id, generation),
  CHECK (expires_at >= created_at),
  CHECK (lease_expires_at IS NULL OR lease_expires_at >= claimed_at),
  -- Claim material exists exactly from CLAIMED onwards (a request that was
  -- cancelled/expired before any claim never had any).
  CHECK ((status = 'PENDING') = (claimed_at IS NULL AND claim_token_digest IS NULL AND lease_expires_at IS NULL)
         OR status IN ('CANCELLED', 'EXPIRED', 'FAILED')),
  CHECK (status != 'CLAIMED' OR (claim_token_digest IS NOT NULL AND claimed_at IS NOT NULL AND lease_expires_at IS NOT NULL)),
  CHECK (status != 'SUCCEEDED' OR claim_token_digest IS NOT NULL),
  CHECK (phase IS NULL OR claimed_at IS NOT NULL),
  CHECK ((status IN ('PENDING', 'CLAIMED')) = (finished_at IS NULL)),
  CHECK ((status IN ('PENDING', 'CLAIMED')) = (outcome_code IS NULL)),
  -- `IS NOT NULL AND ... IN (...)`: SQLite's IN yields NULL for a NULL left
  -- side and a NULL CHECK result passes (see 0006's note), so each terminal
  -- status states its closed outcome set explicitly.
  CHECK (status != 'SUCCEEDED' OR outcome_code IS 'SESSION_STORED'),
  CHECK (status != 'FAILED' OR (outcome_code IS NOT NULL AND outcome_code IN (
         'LOGIN_TIMED_OUT', 'LOGIN_WINDOW_CLOSED', 'LOGIN_PAGE_UNREACHABLE', 'UPLOAD_FAILED',
         'RUNNER_BUSY', 'ACCESS_REVOKED', 'INTERNAL_ERROR'))),
  CHECK (status != 'CANCELLED' OR (outcome_code IS NOT NULL AND outcome_code IN ('CANCELLED_BY_USER', 'RUNNER_SHUTDOWN'))),
  CHECK (status != 'EXPIRED' OR (outcome_code IS NOT NULL AND outcome_code IN ('REQUEST_EXPIRED', 'LEASE_EXPIRED'))));

-- At most one active request per notification account, and at most one
-- active onboarding browser operation per runner (a pending request already
-- reserves the runner's single onboarding slot).
CREATE UNIQUE INDEX uq_notification_onboarding_active_account
  ON notification_onboarding_requests(account_id) WHERE status IN ('PENDING', 'CLAIMED');
CREATE UNIQUE INDEX uq_notification_onboarding_active_runner
  ON notification_onboarding_requests(runner_id) WHERE status IN ('PENDING', 'CLAIMED');
CREATE UNIQUE INDEX uq_notification_onboarding_claimed_runner
  ON notification_onboarding_requests(runner_id) WHERE status = 'CLAIMED';
CREATE INDEX idx_notification_onboarding_expiry
  ON notification_onboarding_requests(expires_at) WHERE status IN ('PENDING', 'CLAIMED');
