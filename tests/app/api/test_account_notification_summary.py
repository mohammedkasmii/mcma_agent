"""GET /accounts carries a per-account notification summary: how much is
waiting, on how many dossiers, and how trustworthy the last refresh was.

The employee works four portal accounts and needs to know which one to open
without visiting each queue. Everything here is derived from the SAME
category_presence and poll_runs rows the work queue and the freshness rules
use -- no new table, no second definition of "new". Synthetic data only.
"""

import pytest

from mcma.notifications.poller import record_failed_refresh_attempt
from api_test_support import (
    MAMDA_OUJDA,
    NADOR,
    OUJDA,
    app_and_client,  # noqa: F401
    conn,  # noqa: F401
    create_user,
    db_path,  # noqa: F401
    grant_access,
    login_client,
)

SUMMARY_FIELDS = (
    "active_notification_count",
    "unread_notification_count",
    "unread_claim_count",
    "notification_last_attempt_at",
    "notification_last_attempt_status",
    "notification_last_success_at",
)


def _add_claim(conn, account_id, portal_claim_id):
    claim_pk = f"{account_id}:{portal_claim_id}"
    conn.execute(
        "INSERT INTO claims (claim_pk, account_id, portal_claim_id, reference, first_seen_version, "
        "last_seen_version) VALUES (?, ?, ?, ?, 1, 1)",
        (claim_pk, account_id, portal_claim_id, f"SIN-{portal_claim_id}"),
    )
    return claim_pk


def _add_presence(conn, account_id, claim_pk, code, *, unread, present=True):
    conn.execute("INSERT OR IGNORE INTO categories (code_alerte, label) VALUES (?, ?)", (code, code))
    conn.execute(
        "INSERT INTO category_presence (account_id, claim_pk, category_code, present, presence_status, "
        "since_version, unread, appeared_poll_version) VALUES (?, ?, ?, ?, ?, 1, ?, 1)",
        (
            account_id,
            claim_pk,
            code,
            int(present),
            "ACTIVE" if present else "RESOLVED_ON_PORTAL",
            int(unread),
        ),
    )


def _add_poll_run(conn, account_id, poll_run_id, status, *, session_valid=True, completed_at=None):
    conn.execute(
        "INSERT INTO poll_runs (poll_run_id, account_id, started_at, completed_at, status, session_valid) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            poll_run_id,
            account_id,
            completed_at or "2026-02-01T08:00:00+00:00",
            completed_at,
            status,
            int(session_valid),
        ),
    )


def _operator(conn, client, *accounts):
    user_id = create_user(conn, "alice", "pw12345", "operator")
    for account_id in accounts:
        grant_access(conn, user_id, account_id)
    return login_client(client, "alice", "pw12345")


def client_of(app_and_client):
    _app, client, _sessions = app_and_client
    return client


def _accounts_by_id(client):
    response = client.get("/accounts")
    assert response.status_code == 200, response.text
    return {account["account_id"]: account for account in response.json()["accounts"]}


# --------------------------------------------------------------------- #
# Counting
# --------------------------------------------------------------------- #


def test_one_dossier_in_two_categories_is_two_notifications_and_one_dossier(conn, app_and_client):
    """The distinction the whole wording change rests on: category
    memberships and dossiers are different numbers."""
    _, client, _ = app_and_client
    claim_pk = _add_claim(conn, OUJDA, "699001")
    _add_presence(conn, OUJDA, claim_pk, "CAT_A", unread=True)
    _add_presence(conn, OUJDA, claim_pk, "CAT_B", unread=True)
    _operator(conn, client, OUJDA)

    account = _accounts_by_id(client)[OUJDA]
    assert account["active_notification_count"] == 2
    assert account["unread_notification_count"] == 2
    assert account["unread_claim_count"] == 1


def test_seen_memberships_count_as_active_but_not_unread(conn, app_and_client):
    _, client, _ = app_and_client
    first = _add_claim(conn, OUJDA, "699001")
    second = _add_claim(conn, OUJDA, "699002")
    _add_presence(conn, OUJDA, first, "CAT_A", unread=True)
    _add_presence(conn, OUJDA, first, "CAT_B", unread=False)
    _add_presence(conn, OUJDA, second, "CAT_A", unread=False)
    _operator(conn, client, OUJDA)

    account = _accounts_by_id(client)[OUJDA]
    assert account["active_notification_count"] == 3
    assert account["unread_notification_count"] == 1
    assert account["unread_claim_count"] == 1


def test_resolved_memberships_are_not_counted_at_all(conn, app_and_client):
    """present=0 is a notification that left the portal. It is not active,
    and it is not new, whatever its unread flag still holds."""
    _, client, _ = app_and_client
    claim_pk = _add_claim(conn, OUJDA, "699001")
    _add_presence(conn, OUJDA, claim_pk, "CAT_A", unread=True, present=False)
    _add_presence(conn, OUJDA, claim_pk, "CAT_B", unread=False, present=False)
    _operator(conn, client, OUJDA)

    account = _accounts_by_id(client)[OUJDA]
    assert account["active_notification_count"] == 0
    assert account["unread_notification_count"] == 0
    assert account["unread_claim_count"] == 0


def test_unread_dossiers_are_counted_distinctly_across_several_claims(conn, app_and_client):
    _, client, _ = app_and_client
    first = _add_claim(conn, OUJDA, "699001")
    second = _add_claim(conn, OUJDA, "699002")
    third = _add_claim(conn, OUJDA, "699003")
    for claim_pk in (first, second):
        _add_presence(conn, OUJDA, claim_pk, "CAT_A", unread=True)
        _add_presence(conn, OUJDA, claim_pk, "CAT_B", unread=True)
    _add_presence(conn, OUJDA, third, "CAT_A", unread=False)
    _operator(conn, client, OUJDA)

    account = _accounts_by_id(client)[OUJDA]
    assert account["unread_notification_count"] == 4
    assert account["unread_claim_count"] == 2


def test_an_account_with_nothing_reports_zeros_not_nulls(conn, app_and_client):
    _, client, _ = app_and_client
    _operator(conn, client, OUJDA)

    account = _accounts_by_id(client)[OUJDA]
    assert account["active_notification_count"] == 0
    assert account["unread_notification_count"] == 0
    assert account["unread_claim_count"] == 0


# --------------------------------------------------------------------- #
# Refresh state
# --------------------------------------------------------------------- #


def test_an_account_that_was_never_polled_reports_null_refresh_state(conn, app_and_client):
    """Never refreshed is not "refreshed long ago": nothing is invented."""
    _, client, _ = app_and_client
    _operator(conn, client, OUJDA)

    account = _accounts_by_id(client)[OUJDA]
    assert account["notification_last_attempt_at"] is None
    assert account["notification_last_attempt_status"] is None
    assert account["notification_last_success_at"] is None


def test_a_failed_latest_attempt_keeps_the_earlier_success_time(conn, app_and_client):
    """The case the warning exists for: the newest attempt failed, so what
    is on screen still dates from the earlier COMPLETE poll and the employee
    must be able to see both facts."""
    _, client, _ = app_and_client
    _add_poll_run(conn, OUJDA, "poll-1", "COMPLETE", completed_at="2026-02-01T08:00:00+00:00")
    _add_poll_run(
        conn, OUJDA, "poll-2", "FAILED", session_valid=False, completed_at="2026-02-01T09:00:00+00:00"
    )
    _operator(conn, client, OUJDA)

    account = _accounts_by_id(client)[OUJDA]
    assert account["notification_last_attempt_status"] == "FAILED"
    assert account["notification_last_attempt_at"] == "2026-02-01T09:00:00+00:00"
    assert account["notification_last_success_at"] == "2026-02-01T08:00:00+00:00"


def test_a_partial_latest_attempt_is_reported_as_partial(conn, app_and_client):
    _, client, _ = app_and_client
    _add_poll_run(conn, OUJDA, "poll-1", "COMPLETE", completed_at="2026-02-01T08:00:00+00:00")
    _add_poll_run(conn, OUJDA, "poll-2", "PARTIAL", completed_at="2026-02-01T09:00:00+00:00")
    _operator(conn, client, OUJDA)

    account = _accounts_by_id(client)[OUJDA]
    assert account["notification_last_attempt_status"] == "PARTIAL"
    assert account["notification_last_success_at"] == "2026-02-01T08:00:00+00:00"


def test_a_complete_poll_on_an_invalid_session_is_not_a_success(conn, app_and_client):
    """session_valid=0 means nothing was truly read -- it must not become
    the "up to date as of" time."""
    _, client, _ = app_and_client
    _add_poll_run(
        conn, OUJDA, "poll-1", "COMPLETE", session_valid=False, completed_at="2026-02-01T08:00:00+00:00"
    )
    _operator(conn, client, OUJDA)

    account = _accounts_by_id(client)[OUJDA]
    assert account["notification_last_attempt_status"] == "COMPLETE"
    assert account["notification_last_success_at"] is None


def test_the_latest_success_is_the_most_recent_one(conn, app_and_client):
    _, client, _ = app_and_client
    _add_poll_run(conn, OUJDA, "poll-1", "COMPLETE", completed_at="2026-02-01T08:00:00+00:00")
    _add_poll_run(conn, OUJDA, "poll-2", "COMPLETE", completed_at="2026-02-02T08:00:00+00:00")
    _operator(conn, client, OUJDA)

    account = _accounts_by_id(client)[OUJDA]
    assert account["notification_last_success_at"] == "2026-02-02T08:00:00+00:00"


def test_a_running_poll_with_no_completed_at_reports_a_null_attempt_time(conn, app_and_client):
    _, client, _ = app_and_client
    _add_poll_run(conn, OUJDA, "poll-1", "PARTIAL", completed_at=None)
    _operator(conn, client, OUJDA)

    account = _accounts_by_id(client)[OUJDA]
    assert account["notification_last_attempt_status"] == "PARTIAL"
    assert account["notification_last_attempt_at"] is None


# --------------------------------------------------------------------- #
# Scope and authorization
# --------------------------------------------------------------------- #


def test_counts_never_mix_two_accounts(conn, app_and_client):
    """Four accounts on one portal: Oujda's volume says nothing about
    Nador's, and the same external dossier under both is two dossiers."""
    _, client, _ = app_and_client
    oujda_claim = _add_claim(conn, OUJDA, "SAME")
    nador_claim = _add_claim(conn, NADOR, "SAME")
    _add_presence(conn, OUJDA, oujda_claim, "CAT_A", unread=True)
    _add_presence(conn, NADOR, nador_claim, "CAT_A", unread=True)
    _add_presence(conn, NADOR, nador_claim, "CAT_B", unread=True)
    _add_poll_run(conn, OUJDA, "poll-o", "COMPLETE", completed_at="2026-02-01T08:00:00+00:00")
    _add_poll_run(
        conn, NADOR, "poll-n", "FAILED", session_valid=False, completed_at="2026-02-01T09:00:00+00:00"
    )
    _operator(conn, client, OUJDA, NADOR)

    accounts = _accounts_by_id(client)
    assert accounts[OUJDA]["unread_notification_count"] == 1
    assert accounts[OUJDA]["unread_claim_count"] == 1
    assert accounts[OUJDA]["notification_last_attempt_status"] == "COMPLETE"
    assert accounts[NADOR]["unread_notification_count"] == 2
    assert accounts[NADOR]["unread_claim_count"] == 1
    assert accounts[NADOR]["notification_last_attempt_status"] == "FAILED"
    assert accounts[NADOR]["notification_last_success_at"] is None


def test_an_inaccessible_accounts_volume_is_never_exposed(conn, app_and_client):
    _, client, _ = app_and_client
    hidden_claim = _add_claim(conn, MAMDA_OUJDA, "699009")
    _add_presence(conn, MAMDA_OUJDA, hidden_claim, "CAT_A", unread=True)
    _add_poll_run(conn, MAMDA_OUJDA, "poll-h", "COMPLETE", completed_at="2026-02-01T08:00:00+00:00")
    _operator(conn, client, OUJDA)

    accounts = _accounts_by_id(client)
    assert set(accounts) == {OUJDA}
    assert accounts[OUJDA]["unread_notification_count"] == 0


def test_the_summary_requires_authentication(conn, app_and_client):
    _, client, _ = app_and_client
    assert client.get("/accounts").status_code == 401


def test_every_summary_field_is_present_on_every_account(conn, app_and_client):
    _, client, _ = app_and_client
    _operator(conn, client, OUJDA, NADOR)

    for account in _accounts_by_id(client).values():
        for field in SUMMARY_FIELDS:
            assert field in account, field
        # The existing fields still mean what they meant.
        assert {"account_id", "label", "entity", "scope", "writable", "connection_state"} <= set(account)


def test_the_summary_exposes_no_claimant_data(conn, app_and_client):
    """Counts and timestamps only: the overview names no insured person,
    reference or registration."""
    _, client, _ = app_and_client
    claim_pk = _add_claim(conn, OUJDA, "699001")
    conn.execute(
        "UPDATE claims SET insured = 'BENALI Youssef', matricule_norm = '77001C3' WHERE claim_pk = ?",
        (claim_pk,),
    )
    _add_presence(conn, OUJDA, claim_pk, "CAT_A", unread=True)
    _operator(conn, client, OUJDA)

    body = client.get("/accounts").text
    assert "BENALI" not in body
    assert "77001C3" not in body
    assert "SIN-699001" not in body
    assert claim_pk not in body


def test_the_summary_is_batched_never_one_query_per_account(conn, app_and_client):
    """The whole point of deriving this server-side is that it costs a fixed
    number of queries. Four accounts must not mean four round trips."""
    _, client, _ = app_and_client
    for account_id in (OUJDA, NADOR, MAMDA_OUJDA):
        claim_pk = _add_claim(conn, account_id, "699001")
        _add_presence(conn, account_id, claim_pk, "CAT_A", unread=True)
        _add_poll_run(conn, account_id, f"poll-{account_id}", "COMPLETE",
                      completed_at="2026-02-01T08:00:00+00:00")
    _operator(conn, client, OUJDA, NADOR, MAMDA_OUJDA)

    executed = []
    original = conn.execute

    def counting(sql, parameters=()):
        executed.append(sql)
        return original(sql, parameters)

    conn.execute = counting
    try:
        accounts = _accounts_by_id(client)
    finally:
        conn.execute = original

    assert len(accounts) == 3
    # One grouped query for the counts, two for the poll timestamps --
    # whatever the number of accounts.
    assert len([sql for sql in executed if "category_presence" in sql]) == 1
    assert len([sql for sql in executed if "poll_runs" in sql]) == 2


# --------------------------------------------------------------------- #
# Attempts that never reached run_poll
# --------------------------------------------------------------------- #
#
# poll_one_account gives up before run_poll on an expired session, a missing
# one, or an unreachable portal. Those attempts used to leave no trace at
# all, so an account whose refreshes had been failing all morning still
# reported yesterday's COMPLETE poll as its latest attempt.


@pytest.mark.parametrize("outcome", ["RECONNECT_REQUIRED", "PORTAL_UNAVAILABLE", "NO_SESSION"])
def test_an_expiry_after_an_earlier_complete_poll_is_the_latest_attempt(
    conn, app_and_client, outcome
):
    """The regression: yesterday succeeded, today's refresh never reached
    the portal. Both facts must survive -- the failure is the latest
    attempt, and the success time is still the earlier COMPLETE poll."""
    _add_poll_run(conn, OUJDA, "poll-1", "COMPLETE", completed_at="2026-02-01T08:00:00+00:00")
    record_failed_refresh_attempt(conn, OUJDA, outcome)
    _operator(conn, client_of(app_and_client), OUJDA)

    account = _accounts_by_id(client_of(app_and_client))[OUJDA]
    assert account["notification_last_attempt_status"] == "FAILED"
    assert account["notification_last_attempt_at"] is not None
    assert account["notification_last_attempt_at"] > "2026-02-01T08:00:00+00:00"
    # The only honest "as of" time is unchanged.
    assert account["notification_last_success_at"] == "2026-02-01T08:00:00+00:00"


def test_an_expiry_leaves_the_notification_counts_untouched(conn, app_and_client):
    """A refresh that read nothing says nothing about what is waiting: the
    counts still describe the last poll that actually read the portal."""
    claim_pk = _add_claim(conn, OUJDA, "699001")
    _add_presence(conn, OUJDA, claim_pk, "CAT_A", unread=True)
    _add_poll_run(conn, OUJDA, "poll-1", "COMPLETE", completed_at="2026-02-01T08:00:00+00:00")
    _operator(conn, client_of(app_and_client), OUJDA)
    before = _accounts_by_id(client_of(app_and_client))[OUJDA]

    record_failed_refresh_attempt(conn, OUJDA, "RECONNECT_REQUIRED")

    after = _accounts_by_id(client_of(app_and_client))[OUJDA]
    for field in ("active_notification_count", "unread_notification_count", "unread_claim_count"):
        assert after[field] == before[field], field
    assert after["unread_notification_count"] == 1


def test_a_successful_poll_after_an_expiry_takes_over_again(conn, app_and_client):
    """Recovery is visible too: a later COMPLETE poll becomes both the
    latest attempt and the new success time."""
    _add_poll_run(conn, OUJDA, "poll-1", "COMPLETE", completed_at="2026-02-01T08:00:00+00:00")
    record_failed_refresh_attempt(conn, OUJDA, "RECONNECT_REQUIRED")
    _add_poll_run(conn, OUJDA, "poll-2", "COMPLETE", completed_at="2026-02-03T08:00:00+00:00")
    _operator(conn, client_of(app_and_client), OUJDA)

    account = _accounts_by_id(client_of(app_and_client))[OUJDA]
    assert account["notification_last_attempt_status"] == "COMPLETE"
    assert account["notification_last_success_at"] == "2026-02-03T08:00:00+00:00"


def test_a_recorded_expiry_never_crosses_into_another_account(conn, app_and_client):
    _add_poll_run(conn, NADOR, "poll-n", "COMPLETE", completed_at="2026-02-01T08:00:00+00:00")
    record_failed_refresh_attempt(conn, OUJDA, "NO_SESSION")
    _operator(conn, client_of(app_and_client), OUJDA, NADOR)

    accounts = _accounts_by_id(client_of(app_and_client))
    assert accounts[OUJDA]["notification_last_attempt_status"] == "FAILED"
    assert accounts[NADOR]["notification_last_attempt_status"] == "COMPLETE"
    assert accounts[NADOR]["notification_last_success_at"] == "2026-02-01T08:00:00+00:00"
