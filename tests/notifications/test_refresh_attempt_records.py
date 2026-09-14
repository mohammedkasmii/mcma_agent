"""A refresh that gives up BEFORE run_poll still happened, and the employee
has to be able to see that.

Five poll exits return early without ever calling run_poll (no session, an
expired session, the portal being unreachable). Nothing was written for any
of them, so yesterday's COMPLETE poll stayed the "latest attempt"
indefinitely while today's refreshes were failing -- the same stale claim
mcma.app.connection_state was built to remove, arriving by another route.

What must NOT happen is equally important: these attempts read nothing, so
they may not advance any category presence, establish any freshness
baseline, or become a "last successful refresh".

Synthetic data only; no portal, no browser, no session material.
"""

import asyncio
import json

import pytest

from mcma.notifications.extract import run_poll
from mcma.notifications.poller import (
    ANNOUNCED_WITHOUT_RUN_OUTCOMES,
    FAILED_BEFORE_POLL_OUTCOMES,
    NOTIFICATIONS_REFRESHED,
    POLL_RUN_OUTCOMES,
    poll_one_account,
    publish_refresh_event,
    record_failed_refresh_attempt,
)
from mcma.persistence.repositories.outbox import AccountStateVersionRepository
from mcma.persistence.leases import acquire_lease
from mcma.persistence.repositories.claims import CategoryPresenceRepository
from notifications_test_support import CATEGORY, NADOR, OUJDA, StubReader, seed_claim


def _poll(conn, account_id=OUJDA, **overrides):
    """The real poll entry point, with nothing behind it. Every argument
    the portal would need is inert: the run gives up long before it could
    be used."""
    kwargs = {
        "instance_id": "instance-1",
        "allowed_host": "portal.test",
        "vault_dir": None,
        "crypto_backend": None,
    }
    kwargs.update(overrides)
    return asyncio.run(poll_one_account(conn, object(), account_id, (), **kwargs))


def _poll_runs(conn, account_id=OUJDA):
    return conn.execute(
        "SELECT * FROM poll_runs WHERE account_id = ? ORDER BY rowid", (account_id,)
    ).fetchall()


def _events(conn, account_id=OUJDA):
    return conn.execute(
        "SELECT * FROM event_outbox WHERE account_id = ? ORDER BY event_id", (account_id,)
    ).fetchall()


# --------------------------------------------------------------------- #
# Recording the attempt
# --------------------------------------------------------------------- #


def test_an_attempt_with_no_session_is_recorded_as_a_failed_run(conn):
    """No stored session -> NO_SESSION, and the attempt is on the record."""
    assert _poll(conn) == "NO_SESSION"

    runs = _poll_runs(conn)
    assert len(runs) == 1
    assert runs[0]["status"] == "FAILED"
    assert runs[0]["session_valid"] == 0
    assert runs[0]["completed_at"] is not None


def test_a_recorded_attempt_advances_no_category_presence(conn):
    """The row exists so the attempt is visible -- not so that anything is
    concluded from it. A poll that read nothing must leave every
    membership exactly as it was."""
    seed_claim(conn, OUJDA, "claim-1", "IDS-1")
    presence = CategoryPresenceRepository(conn)
    presence.ensure_row(OUJDA, "claim-1", CATEGORY, since_version=1)
    before = presence.get(OUJDA, "claim-1", CATEGORY)
    assert before is not None
    before = dict(before)

    _poll(conn)

    after = presence.get(OUJDA, "claim-1", CATEGORY)
    assert after is not None
    assert dict(after) == before
    # No per-category evidence was written either, so nothing downstream
    # can mistake this for a category that was read.
    assert conn.execute("SELECT COUNT(*) AS c FROM poll_run_categories").fetchone()["c"] == 0


def test_a_recorded_attempt_establishes_no_freshness_baseline(conn):
    """A baseline means "everything present now is existing work". An
    attempt that read nothing cannot make that claim."""
    _poll(conn)
    assert conn.execute("SELECT COUNT(*) AS c FROM category_baselines").fetchone()["c"] == 0


def test_a_deferred_refresh_records_nothing(conn):
    """LEASE_BUSY is a refresh that waited for a dossier fill, not one that
    failed. Recording it would put a false warning on a healthy account."""
    acquire_lease(conn, OUJDA, "another-instance", ttl_seconds=180)

    assert _poll(conn) == "LEASE_BUSY"
    assert _poll_runs(conn) == []
    assert _events(conn) == []


def test_each_attempt_is_recorded_for_its_own_account_only(conn):
    _poll(conn, account_id=OUJDA)
    _poll(conn, account_id=OUJDA)
    _poll(conn, account_id=NADOR)

    assert len(_poll_runs(conn, OUJDA)) == 2
    assert len(_poll_runs(conn, NADOR)) == 1


def test_each_outcome_belongs_to_exactly_one_treatment(conn):
    """Pinned so a new early return is a deliberate decision: recorded and
    announced, announced only, or neither."""
    assert FAILED_BEFORE_POLL_OUTCOMES == {"NO_SESSION", "RECONNECT_REQUIRED", "PORTAL_UNAVAILABLE"}
    assert POLL_RUN_OUTCOMES == {"POLLED", "POLL_INCOMPLETE", "POLL_FAILED"}
    assert ANNOUNCED_WITHOUT_RUN_OUTCOMES == {"NO_CATEGORIES"}
    assert not FAILED_BEFORE_POLL_OUTCOMES & POLL_RUN_OUTCOMES
    assert not ANNOUNCED_WITHOUT_RUN_OUTCOMES & (FAILED_BEFORE_POLL_OUTCOMES | POLL_RUN_OUTCOMES)
    # A deferred refresh is none of the three: nothing changed.
    assert "LEASE_BUSY" not in (
        FAILED_BEFORE_POLL_OUTCOMES | POLL_RUN_OUTCOMES | ANNOUNCED_WITHOUT_RUN_OUTCOMES
    )


@pytest.mark.parametrize("outcome", sorted(FAILED_BEFORE_POLL_OUTCOMES))
def test_every_pre_poll_failure_is_recordable(conn, outcome):
    record_failed_refresh_attempt(conn, OUJDA, outcome)

    runs = _poll_runs(conn)
    assert len(runs) == 1
    assert runs[0]["status"] == "FAILED"
    assert runs[0]["session_valid"] == 0


# --------------------------------------------------------------------- #
# Announcing it
# --------------------------------------------------------------------- #


def test_a_failed_attempt_publishes_one_event(conn):
    _poll(conn)

    events = _events(conn)
    assert len(events) == 1
    assert events[0]["type"] == NOTIFICATIONS_REFRESHED
    assert events[0]["aggregate"] == "notification"
    assert json.loads(events[0]["payload_json"]) == {"outcome": "NO_SESSION"}


def test_the_event_payload_carries_no_claim_data(conn):
    """The outbox is documented PII-free. This one publishes an enum."""
    seed_claim(conn, OUJDA, "claim-1", "IDS-SECRET")
    publish_refresh_event(conn, OUJDA, "POLLED")

    payload = json.loads(_events(conn)[0]["payload_json"])
    assert set(payload) == {"outcome"}
    assert payload["outcome"] == "POLLED"
    body = _events(conn)[0]["payload_json"]
    for forbidden in ("IDS-SECRET", "claim-1", "reference", "insured"):
        assert forbidden not in body


def test_an_event_belongs_to_the_account_it_concerns(conn):
    """The SSE layer filters by the outbox row's account_id, so this is
    what keeps one agency's refresh out of another's stream."""
    publish_refresh_event(conn, NADOR, "POLLED")

    assert _events(conn, OUJDA) == []
    assert len(_events(conn, NADOR)) == 1


def test_bookkeeping_failure_never_changes_the_poll_outcome(conn, monkeypatch):
    """A refresh that worked must not be reported as broken by its own
    record-keeping."""
    import mcma.notifications.poller as poller_module

    def explode(*_args, **_kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(poller_module, "record_failed_refresh_attempt", explode)

    assert _poll(conn) == "NO_SESSION"


# --------------------------------------------------------------------- #
# One transaction: the state and the event that announces it
# --------------------------------------------------------------------- #


def _break_the_outbox(monkeypatch):
    """Makes only the outbox insert fail, leaving every other write able to
    succeed -- which is what exposes a non-atomic pair."""
    import mcma.persistence.repositories.outbox as outbox_module

    def explode(*_args, **_kwargs):
        raise RuntimeError("outbox unavailable")

    monkeypatch.setattr(outbox_module.EventOutboxRepository, "insert", explode)


def test_a_failed_attempt_and_its_event_commit_together(conn, monkeypatch):
    """The transactional-outbox rule: if the event cannot be written, the
    poll_runs row it describes must not exist either. Otherwise an account
    reads "derniere tentative echouee" on a screen that was never told to
    look again."""
    _break_the_outbox(monkeypatch)

    with pytest.raises(RuntimeError):
        record_failed_refresh_attempt(conn, OUJDA, "NO_SESSION")

    assert _poll_runs(conn) == []
    assert _events(conn) == []


def test_a_rolled_back_attempt_consumes_no_state_version(conn, monkeypatch):
    """The version is allocated inside the same transaction, so a failed
    attempt does not leave a gap that looks like a lost event."""
    before = AccountStateVersionRepository(conn).current(OUJDA)
    _break_the_outbox(monkeypatch)

    with pytest.raises(RuntimeError):
        record_failed_refresh_attempt(conn, OUJDA, "NO_SESSION")

    assert AccountStateVersionRepository(conn).current(OUJDA) == before


def test_a_poll_and_its_event_commit_together(conn):
    """Same rule on the path that DOES read: the claims, the poll run, the
    presence rows and the event are one commit."""
    reader = StubReader({CATEGORY: [{"idSinistre": "A", "reference": "R-A"}]})

    def publish(txn_conn, version, run_status):
        raise RuntimeError("outbox unavailable")

    with pytest.raises(RuntimeError):
        asyncio.run(run_poll(conn, OUJDA, reader, [CATEGORY], publish=publish))

    # Nothing survived: not the run, not the claim it read, not the event.
    assert _poll_runs(conn) == []
    assert conn.execute("SELECT COUNT(*) AS c FROM claims").fetchone()["c"] == 0
    assert conn.execute("SELECT COUNT(*) AS c FROM category_presence").fetchone()["c"] == 0
    assert _events(conn) == []


def test_a_successful_poll_writes_its_rows_and_its_event(conn):
    reader = StubReader({CATEGORY: [{"idSinistre": "A", "reference": "R-A"}]})
    published = []

    def publish(txn_conn, version, run_status):
        published.append((version, run_status))
        from mcma.notifications.poller import _insert_refresh_event

        _insert_refresh_event(txn_conn, OUJDA, version, "POLLED")

    asyncio.run(run_poll(conn, OUJDA, reader, [CATEGORY], publish=publish))

    assert len(_poll_runs(conn)) == 1
    events = _events(conn)
    assert len(events) == 1
    # The event carries the very version the poll stamped on its rows.
    assert published[0][1] == "COMPLETE"
    assert events[0]["account_state_version"] == published[0][0]
    assert AccountStateVersionRepository(conn).current(OUJDA) == published[0][0]


def test_no_write_transaction_is_held_while_the_portal_is_read(conn):
    """A SQLite write lock held across a network read would block every
    other writer for as long as the portal takes to answer. Proven from
    inside the read itself: BEGIN IMMEDIATE would raise if a transaction
    were already open on this connection."""
    probed = []

    class _ProbingReader:
        async def read_notifications(self, code):
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("COMMIT")
            probed.append(code)
            return [{"idSinistre": "A", "reference": "R-A"}]

    asyncio.run(run_poll(conn, OUJDA, _ProbingReader(), [CATEGORY], version=1))

    assert probed == [CATEGORY]
    assert len(_poll_runs(conn)) == 1


def test_repeated_failures_each_get_their_own_state_version(conn):
    """current() would publish two different failures under one version,
    making the second look like a replay of the first."""
    _poll(conn)
    _poll(conn)
    _poll(conn)

    versions = [row["account_state_version"] for row in _events(conn)]
    assert len(versions) == 3
    assert versions == sorted(versions)
    assert len(set(versions)) == 3
    assert AccountStateVersionRepository(conn).current(OUJDA) == versions[-1]


# --------------------------------------------------------------------- #
# NO_CATEGORIES: nothing read, but something changed
# --------------------------------------------------------------------- #


class _EmptyDiscoveryReader:
    """An authenticated session that simply has no open alert category."""

    async def observe_session_state(self):
        return "AUTHENTICATED"

    async def discover_notification_categories(self):
        return []

    async def close(self):
        return None


def _poll_with_no_categories(conn, monkeypatch, observed):
    import mcma.notifications.poller as poller_module
    from mcma.portal.sinauto_contracts import DEFAULT_SINAUTO_HOST

    async def _open_reader(*_args, **_kwargs):
        return _EmptyDiscoveryReader()

    monkeypatch.setattr(
        poller_module, "load_and_verify_session",
        lambda *a, **k: b'{"cookies": [], "origins": []}',
    )
    monkeypatch.setattr(poller_module, "open_reader", _open_reader)

    return asyncio.run(
        poller_module.poll_one_account(
            conn, object(), OUJDA, (),
            instance_id="instance-1", allowed_host=DEFAULT_SINAUTO_HOST,
            vault_dir=None, crypto_backend=None, entity="MCMA",
            session_observer=lambda account_id, state: observed.append((account_id, state)),
        )
    )


def test_an_empty_but_authenticated_account_is_announced(conn, monkeypatch):
    """NO_CATEGORIES reads nothing, so there is no poll to record -- but it
    proves the session is live, which moves /accounts from UNVERIFIED to
    CONNECTED. A change nobody is told about is a stale screen."""
    observed = []

    assert _poll_with_no_categories(conn, monkeypatch, observed) == "NO_CATEGORIES"

    # The state change that makes the event necessary.
    assert ("acct-oujda", "AUTHENTICATED") in observed
    events = _events(conn)
    assert len(events) == 1
    assert events[0]["type"] == NOTIFICATIONS_REFRESHED
    assert json.loads(events[0]["payload_json"]) == {"outcome": "NO_CATEGORIES"}


def test_an_empty_account_is_never_recorded_as_a_failed_refresh(conn, monkeypatch):
    """It is not a failure: a warning here would tell the employee their
    notifications are broken when the account is simply quiet."""
    _poll_with_no_categories(conn, monkeypatch, [])

    assert _poll_runs(conn) == []


def test_an_empty_account_still_advances_its_state_version(conn, monkeypatch):
    before = AccountStateVersionRepository(conn).current(OUJDA)

    _poll_with_no_categories(conn, monkeypatch, [])

    assert AccountStateVersionRepository(conn).current(OUJDA) > before
