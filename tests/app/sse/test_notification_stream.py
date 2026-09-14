"""A background notification poll reaches an employee who is already
looking at the screen.

The stream has no client-side polling interval and the frontend does not
reconnect on a timer, so an event published while a session is ALREADY
CONNECTED has to be delivered on that same connection. These cases hold a
stream open across the publish rather than reconnecting afterwards, because
a reconnect would hide exactly the bug that matters.
"""

import asyncio
import json

from mcma.app.sse import stream_events
from mcma.notifications.poller import NOTIFICATIONS_REFRESHED, publish_refresh_event
# conn/db_path come from this directory's conftest.
from sse_test_support import ACCOUNT_A, ACCOUNT_B, StubAuthorizer

PRINCIPAL = object()


def _drain(conn, authorizer, publish, *, iterations=3):
    """Runs a stream that is already connected (no cursor, starting from
    "now"), then lets `publish` happen while it is asleep between polls --
    the real sequence when a background poll lands mid-session."""
    delivered = []
    published = []

    async def scenario():
        async def sleep(_seconds):
            if not published:
                published.append(True)
                publish()

        stream = stream_events(
            conn, PRINCIPAL, authorizer, last_event_id=None, sleep=sleep, max_iterations=iterations
        )
        async for item in stream:
            delivered.append(item)

    asyncio.run(scenario())
    return delivered


def test_an_already_connected_session_receives_a_background_refresh(conn):
    authorizer = StubAuthorizer({ACCOUNT_A})

    delivered = _drain(conn, authorizer, lambda: publish_refresh_event(conn, ACCOUNT_A, "POLLED"))

    assert len(delivered) == 1
    assert delivered[0]["event"] == NOTIFICATIONS_REFRESHED
    assert json.loads(delivered[0]["data"]) == {"outcome": "POLLED"}
    # Delivered on the open connection: no resync was needed to see it.
    assert all(item["event"] != "resync" for item in delivered)


def test_a_failed_background_attempt_is_delivered_too(conn):
    """The overview shows "derniere tentative echouee" from the same data,
    so the warning has to arrive without a page reload."""
    authorizer = StubAuthorizer({ACCOUNT_A})

    delivered = _drain(
        conn, authorizer, lambda: publish_refresh_event(conn, ACCOUNT_A, "RECONNECT_REQUIRED")
    )

    assert len(delivered) == 1
    assert json.loads(delivered[0]["data"]) == {"outcome": "RECONNECT_REQUIRED"}


def test_another_accounts_refresh_never_reaches_this_stream(conn):
    """One office, four accounts: the stream carries only what this
    principal may see, and a refresh event is no exception."""
    authorizer = StubAuthorizer({ACCOUNT_A})

    delivered = _drain(conn, authorizer, lambda: publish_refresh_event(conn, ACCOUNT_B, "POLLED"))

    assert delivered == []


def test_several_accounts_refreshing_are_all_delivered_in_order(conn):
    authorizer = StubAuthorizer({ACCOUNT_A, ACCOUNT_B})

    def publish_both():
        publish_refresh_event(conn, ACCOUNT_A, "POLLED")
        publish_refresh_event(conn, ACCOUNT_B, "POLL_INCOMPLETE")

    delivered = _drain(conn, authorizer, publish_both)

    assert [json.loads(item["data"])["outcome"] for item in delivered] == [
        "POLLED",
        "POLL_INCOMPLETE",
    ]
    # Ids are the outbox cursor, so a reconnect can resume after them.
    assert [item["id"] for item in delivered] == sorted(item["id"] for item in delivered)


def test_a_quiet_poll_interval_delivers_nothing(conn):
    """No event, no traffic: the stream must not invent activity."""
    authorizer = StubAuthorizer({ACCOUNT_A})

    assert _drain(conn, authorizer, lambda: None) == []


def test_an_authenticated_but_empty_account_reaches_the_open_stream(conn):
    """NO_CATEGORIES writes no poll run at all -- nothing was read -- but
    reaching it PROVED the session is live, which flips /accounts from
    "Connexion a verifier" to "Connecte". A change with no event would sit
    unseen on an open screen until the employee navigated."""
    authorizer = StubAuthorizer({ACCOUNT_A})

    delivered = _drain(
        conn, authorizer, lambda: publish_refresh_event(conn, ACCOUNT_A, "NO_CATEGORIES")
    )

    assert len(delivered) == 1
    assert delivered[0]["event"] == NOTIFICATIONS_REFRESHED
    assert json.loads(delivered[0]["data"]) == {"outcome": "NO_CATEGORIES"}
    # Announced without inventing a refresh that never happened.
    assert conn.execute("SELECT COUNT(*) AS c FROM poll_runs").fetchone()["c"] == 0


def test_two_refreshes_on_one_open_stream_are_both_delivered(conn):
    """Consecutive attempts carry distinct state versions, so the second is
    a new event rather than a replay the cursor would skip."""
    authorizer = StubAuthorizer({ACCOUNT_A})

    def publish_twice():
        publish_refresh_event(conn, ACCOUNT_A, "NO_CATEGORIES")
        publish_refresh_event(conn, ACCOUNT_A, "NO_CATEGORIES")

    delivered = _drain(conn, authorizer, publish_twice)

    assert len(delivered) == 2
    versions = [
        row["account_state_version"]
        for row in conn.execute("SELECT account_state_version FROM event_outbox ORDER BY event_id")
    ]
    assert versions == sorted(versions)
    assert len(set(versions)) == 2
