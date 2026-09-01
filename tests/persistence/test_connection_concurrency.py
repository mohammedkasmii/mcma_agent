"""
The V2 employee UI drives several requests at once and holds an SSE stream,
so the one API connection is genuinely used from several threads.

Before mcma.persistence.db.SerializedConnection this raised
`sqlite3.InterfaceError: bad parameter or other API misuse` -- observed on
Windows/Python 3.14 during real browser E2E, surfacing inside the principal
lookup in mcma/app/api/deps.py and therefore looking like an authentication
failure rather than the concurrency bug it was.

These tests drive the SAME connection object the application uses. They do
not mock sqlite, and they do not serialise the callers.
"""

from __future__ import annotations

import threading
import time

import pytest

from mcma.app.sse import compute_replay
from mcma.persistence.db import SerializedConnection, open_database


class _Authorizer:
    """The SSE stream re-checks authorization every pass; the real one reads
    this same connection. A stub keeps the test about concurrency."""

    def __init__(self, accounts):
        self._accounts = set(accounts)

    def visible_accounts(self, principal):
        return self._accounts

    def is_authorized(self, principal, account_id):
        return account_id in self._accounts


@pytest.fixture()
def conn(tmp_path):
    connection = open_database(tmp_path / "concurrency.sqlite3")
    connection.execute(
        "INSERT INTO accounts (account_id, label, entity, scope, active, created_at) "
        "VALUES ('acct-1', 'Account 1', 'MCMA', 'ZONE-A', 1, '2026-01-01T00:00:00+00:00')"
    )
    yield connection
    connection.close()


def _run_concurrently(workers, seconds=1.5):
    """Runs every worker at once for a fixed window and re-raises the first
    failure on the main thread."""
    errors: list[BaseException] = []
    stop = threading.Event()

    def wrap(worker):
        def run():
            try:
                while not stop.is_set():
                    worker()
            except BaseException as exc:  # noqa: BLE001 - re-raised below
                errors.append(exc)
                stop.set()

        return run

    threads = [threading.Thread(target=wrap(worker), daemon=True) for worker in workers]
    for thread in threads:
        thread.start()
    time.sleep(seconds)
    stop.set()
    for thread in threads:
        thread.join(timeout=10)
    if errors:
        raise errors[0]


def test_the_connection_is_a_serialized_one(conn):
    """The raw sqlite3 connection is never handed out: serialization cannot
    be bypassed by a caller that simply asks the factory for a connection."""
    assert isinstance(conn, SerializedConnection)


def test_concurrent_reads_and_sse_replay_do_not_misuse_the_connection(conn):
    """Several 'request handler' threads plus the SSE replay path, all on one
    connection, exactly as Starlette's worker threads and the event loop do
    it. Any InterfaceError fails this test."""
    authorizer = _Authorizer({"acct-1"})

    def principal_lookup():
        # The statement the reported traceback died on.
        conn.execute("SELECT user_id, username, role, active FROM users WHERE user_id = ?", ("u1",)).fetchone()

    def read_accounts():
        conn.execute("SELECT * FROM accounts").fetchall()

    def read_jobs():
        conn.execute("SELECT * FROM automation_jobs").fetchall()

    def sse_replay():
        compute_replay(conn, principal=None, authorizer=authorizer, last_event_id=0)

    _run_concurrently([principal_lookup, read_accounts, read_jobs, sse_replay, read_accounts])


def test_concurrent_writers_share_one_connection_without_error(conn):
    """Writes interleaved with reads. Under the old model the second thread's
    statement could land while the first was mid-operation."""
    counter = {"n": 0}
    guard = threading.Lock()

    def insert_event():
        with guard:
            counter["n"] += 1
            number = counter["n"]
        conn.execute(
            "INSERT INTO event_outbox (account_id, account_state_version, aggregate, type, "
            "payload_json, created_at, published_at) VALUES ('acct-1', ?, 'job', 'JOB_STATUS_CHANGED', "
            "'{}', '2026-01-01T00:00:00+00:00', NULL)",
            (number,),
        )

    def read_events():
        conn.execute("SELECT * FROM event_outbox ORDER BY event_id").fetchall()

    _run_concurrently([insert_event, read_events, read_events])
    rows = conn.execute("SELECT COUNT(*) AS n FROM event_outbox").fetchone()
    assert rows["n"] > 0


def test_an_explicit_transaction_is_not_interleaved(conn):
    """A multi-statement transaction holds the connection from BEGIN through
    COMMIT, so another thread's write cannot land in the middle of it. This
    is what keeps transition() and acquire_lease() atomic now that more than
    one thread genuinely reaches this connection."""
    observed: list[str] = []
    inside = threading.Event()
    released = threading.Event()

    def transaction():
        conn.execute("BEGIN IMMEDIATE")
        try:
            observed.append("tx-start")
            inside.set()
            # Long enough that an unserialized writer would interleave here.
            time.sleep(0.3)
            observed.append("tx-end")
        finally:
            conn.execute("COMMIT")
        released.set()

    def other_writer():
        inside.wait(timeout=5)
        conn.execute(
            "INSERT INTO accounts (account_id, label, entity, scope, active, created_at) "
            "VALUES ('acct-2', 'Account 2', 'MCMA', 'ZONE-B', 1, '2026-01-01T00:00:00+00:00')"
        )
        observed.append("other-write")

    threads = [threading.Thread(target=transaction), threading.Thread(target=other_writer)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert released.is_set()
    assert observed == ["tx-start", "tx-end", "other-write"]


def test_a_failed_transaction_releases_the_connection(conn):
    """A rolled-back transaction must not leave the lock held -- a leak here
    would deadlock every later request rather than fail one."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("INSERT INTO accounts (account_id) VALUES ('broken')")
    except Exception:
        conn.execute("ROLLBACK")

    done = threading.Event()

    def later_request():
        conn.execute("SELECT * FROM accounts").fetchall()
        done.set()

    thread = threading.Thread(target=later_request, daemon=True)
    thread.start()
    thread.join(timeout=5)
    assert done.is_set(), "the connection was still locked after a rolled-back transaction"
