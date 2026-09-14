-- Forward-only. Notification freshness ("Nouveau" / "Vu") for the single
-- employee who works the notification queue -- shared state, not per-user
-- read receipts.
--
-- Freshness belongs to ONE category membership, (account_id, claim_pk,
-- category_code), so it extends category_presence rather than living on
-- the claim: the same dossier in two categories is two notifications. It
-- is NOT the employee workflow status (employee_actions), which viewing a
-- notification never changes.
--
--   unread                 1 while the current appearance has not been viewed
--   appeared_poll_version  the COMPLETE poll that started the current
--                          appearance -- NULL until a complete poll sees it
--   appeared_at, seen_at   when the current appearance started / was viewed
--
-- Rows that already exist were on screen before this feature, so they stay
-- seen (unread defaults to 0) and are recorded as having appeared: the next
-- ordinary poll must not turn them into new notifications.
ALTER TABLE category_presence ADD COLUMN unread INTEGER NOT NULL DEFAULT 0 CHECK (unread IN (0, 1));
ALTER TABLE category_presence ADD COLUMN appeared_poll_version INTEGER;
ALTER TABLE category_presence ADD COLUMN appeared_at TEXT;
ALTER TABLE category_presence ADD COLUMN seen_at TEXT;
UPDATE category_presence SET appeared_poll_version = COALESCE(last_complete_poll_version, since_version);

-- The first COMPLETE, valid-session poll of a category for an account is
-- that category's freshness baseline: everything present then is existing
-- work, never new. Recorded once and never moved. baseline_poll_version is
-- the poll_runs rowid, the same monotonic version presence already uses.
--
-- Backfilled from the complete category polls this database already holds,
-- so an installation that has been polling keeps reporting genuinely new
-- arrivals as new rather than re-baselining after the upgrade. A category
-- that has only ever FAILED gets no baseline here.
CREATE TABLE category_baselines (
  account_id            TEXT NOT NULL REFERENCES accounts(account_id),
  category_code         TEXT NOT NULL REFERENCES categories(code_alerte),
  baseline_poll_version INTEGER NOT NULL,
  established_at        TEXT NOT NULL,
  PRIMARY KEY (account_id, category_code));

INSERT INTO category_baselines (account_id, category_code, baseline_poll_version, established_at)
SELECT r.account_id, c.category_code, MIN(r.rowid), MIN(COALESCE(c.completed_at, r.started_at))
FROM poll_run_categories c JOIN poll_runs r ON r.poll_run_id = c.poll_run_id
WHERE c.status = 'COMPLETE' AND c.session_valid = 1
GROUP BY r.account_id, c.category_code;
