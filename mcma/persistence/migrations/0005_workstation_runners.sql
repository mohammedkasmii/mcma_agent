-- Forward-only. Central registry of Windows workstation runners (Phase 1A):
-- one-time pairing codes, durable runner identities, per-runner MCMA session
-- readiness. Registry ONLY: no job claiming, dispatch or locks live here.
--
-- What is deliberately NOT stored anywhere below: portal usernames or
-- passwords, browser cookies or storage state, OTP values, employee
-- passwords, raw pairing codes, raw runner credentials, Windows usernames or
-- host inventory, free-text client status. Only SHA-256 digests of two
-- high-entropy (256-bit) random secrets are kept.
--
-- "Online" is NOT stored. It is derived from server time and last_seen_at.
--
-- Historical and revoked runners are retained (status REVOKED, never deleted).

-- A pairing code: single use, expiring, bound to the administrator who
-- created it and to ONE target employee. code_digest is the SHA-256 hex of
-- the code, UNIQUE so a digest lookup is an index seek.
CREATE TABLE runner_enrollments (
  enrollment_id      TEXT PRIMARY KEY,
  code_digest        TEXT NOT NULL UNIQUE CHECK (length(code_digest) = 64),
  target_user_id     TEXT NOT NULL REFERENCES users(user_id),
  created_by_user_id TEXT NOT NULL REFERENCES users(user_id),
  runner_label       TEXT CHECK (runner_label IS NULL OR length(runner_label) BETWEEN 1 AND 40),
  created_at         TEXT NOT NULL,
  expires_at         TEXT NOT NULL,
  consumed_at        TEXT,
  revoked_at         TEXT,
  revoked_by_user_id TEXT REFERENCES users(user_id),
  CHECK (consumed_at IS NULL OR revoked_at IS NULL));

CREATE INDEX idx_runner_enrollments_target ON runner_enrollments(target_user_id);

-- A registered runner. credential_digest is the SHA-256 hex of the bearer
-- secret (UNIQUE: the authentication lookup). One enrollment yields at most
-- one runner. status/revoked_at move together (CHECK).
CREATE TABLE runners (
  runner_id          TEXT PRIMARY KEY,
  user_id            TEXT NOT NULL REFERENCES users(user_id),
  credential_digest  TEXT NOT NULL UNIQUE CHECK (length(credential_digest) = 64),
  runner_label       TEXT NOT NULL CHECK (length(runner_label) BETWEEN 1 AND 40),
  status             TEXT NOT NULL CHECK (status IN ('ACTIVE', 'REVOKED')),
  protocol_version   INTEGER CHECK (protocol_version IS NULL OR protocol_version BETWEEN 1 AND 1000),
  app_version        TEXT CHECK (app_version IS NULL OR length(app_version) BETWEEN 1 AND 32),
  enrollment_id      TEXT NOT NULL UNIQUE REFERENCES runner_enrollments(enrollment_id),
  created_at         TEXT NOT NULL,
  last_seen_at       TEXT,
  revoked_at         TEXT,
  revoked_by_user_id TEXT REFERENCES users(user_id),
  CHECK ((status = 'REVOKED') = (revoked_at IS NOT NULL)));

-- MVP rule, enforced by the database: at most ONE active runner per employee.
CREATE UNIQUE INDEX uq_runners_one_active_per_user ON runners(user_id) WHERE status = 'ACTIVE';
CREATE INDEX idx_runners_user ON runners(user_id);
CREATE INDEX idx_runners_status_last_seen ON runners(status, last_seen_at);

-- What a runner reports about each canonical MCMA account it can work on.
-- The account CHECK is the database-level MAMDA/unknown-account rejection:
-- only MCMA Oujda and MCMA Nador may ever appear here.
CREATE TABLE runner_account_capabilities (
  runner_id     TEXT NOT NULL REFERENCES runners(runner_id),
  account_id    TEXT NOT NULL REFERENCES accounts(account_id)
                CHECK (account_id IN ('acct-mcma-oujda', 'acct-mcma-nador')),
  session_state TEXT NOT NULL
                CHECK (session_state IN ('NOT_CONFIGURED', 'LOGIN_REQUIRED', 'READY', 'ERROR')),
  updated_at    TEXT NOT NULL,
  PRIMARY KEY (runner_id, account_id));
