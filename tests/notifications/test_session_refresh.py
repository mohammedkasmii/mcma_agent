"""INC-14 -- the scheduled session-refresh poller runs under the account
lease and escalates on repeated failure (review TR-F31)."""

from mcma.notifications.session_refresh import ESCALATE_AFTER_CONSECUTIVE_FAILURES, refresh_account_session
from notifications_test_support import OUJDA


def test_session_refresh_poller_runs_under_lease_and_escalates_on_repeated_failure(conn):
    escalations = []

    def escalate(account_id, count):
        escalations.append((account_id, count))

    failing_count = ESCALATE_AFTER_CONSECUTIVE_FAILURES - 1
    consecutive = 0
    for _ in range(failing_count):
        consecutive = refresh_account_session(
            conn, OUJDA, "instance-1", refresh_check=lambda: False, escalate=escalate,
            consecutive_failures=consecutive,
        )
        assert escalations == []  # not yet at threshold

    consecutive = refresh_account_session(
        conn, OUJDA, "instance-1", refresh_check=lambda: False, escalate=escalate, consecutive_failures=consecutive
    )
    assert escalations == [(OUJDA, ESCALATE_AFTER_CONSECUTIVE_FAILURES)]

    # A subsequent success resets the counter.
    consecutive = refresh_account_session(
        conn, OUJDA, "instance-1", refresh_check=lambda: True, escalate=escalate, consecutive_failures=consecutive
    )
    assert consecutive == 0


def test_session_refresh_releases_the_lease_after_each_run(conn):
    refresh_account_session(conn, OUJDA, "instance-1", refresh_check=lambda: True, escalate=lambda *a: None)
    assert conn.execute("SELECT COUNT(*) AS c FROM account_leases WHERE account_id=?", (OUJDA,)).fetchone()["c"] == 0


def test_session_refresh_check_exception_counts_as_failure(conn):
    def _raises():
        raise RuntimeError("portal unreachable")

    result = refresh_account_session(conn, OUJDA, "instance-1", refresh_check=_raises, escalate=lambda *a: None)
    assert result == 1
