"""
The four connection states, and the rule that persisted session material
alone never means CONNECTED.

The bug this covers: an account signed in yesterday still reported
CONNECTED this morning and offered "Actualiser", because /accounts read
one column -- portal_sessions.status -- that nothing ages out and only an
explicit revoke clears.
"""

from __future__ import annotations

import threading

from mcma.app.connection_state import (
    CONNECTED,
    NOT_CONNECTED,
    RECONNECT_REQUIRED,
    UNVERIFIED,
    ConnectionStateTracker,
    resolve_connection_state,
)

OUJDA = "acct-test-mcma-a"
NADOR = "acct-test-mcma-b"
MAMDA_A = "acct-test-mamda-a"
MAMDA_B = "acct-test-mamda-b"


def _state(active: bool, history: bool, verified: bool) -> str:
    return resolve_connection_state(
        has_active_session=active, has_session_history=history, verified_live=verified
    )


def test_stored_active_material_alone_is_unverified():
    """A fresh process has observed nothing. The database says material
    exists, which is not the same claim as "it works"."""
    assert _state(active=True, history=True, verified=False) == UNVERIFIED


def test_an_old_successful_poll_does_not_make_it_connected():
    """Deliberately no poll_runs input. Several poll exits return before a
    poll_run is written, so yesterday's COMPLETE row can stay the latest
    one while today's session is dead -- which would reproduce the same
    stale claim through a different route."""
    tracker = ConnectionStateTracker()
    # Whatever happened yesterday, this process has seen nothing.
    assert tracker.is_verified(OUJDA) is False
    assert _state(active=True, history=True, verified=tracker.is_verified(OUJDA)) == UNVERIFIED


def test_live_evidence_makes_it_connected():
    tracker = ConnectionStateTracker()
    tracker.mark_authenticated(OUJDA)
    assert _state(active=True, history=True, verified=tracker.is_verified(OUJDA)) == CONNECTED


def test_a_completed_manual_login_is_evidence():
    """capture_session_for_account returns only after
    perform_manual_login() has positively observed the logged-in markers;
    every other outcome raises. So the employee is not asked to verify
    what they have just done."""
    tracker = ConnectionStateTracker()
    tracker.mark_authenticated(OUJDA)
    assert tracker.is_verified(OUJDA) is True


def test_an_indeterminate_observation_drops_back_to_unverified():
    tracker = ConnectionStateTracker()
    tracker.mark_authenticated(OUJDA)
    tracker.mark_unverified(OUJDA)
    assert _state(active=True, history=True, verified=tracker.is_verified(OUJDA)) == UNVERIFIED


def test_a_logged_out_observation_clears_the_live_evidence():
    tracker = ConnectionStateTracker()
    tracker.mark_authenticated(OUJDA)
    tracker.mark_logged_out(OUJDA)
    assert tracker.is_verified(OUJDA) is False
    # The revoke is the poller's job; once the row is no longer ACTIVE the
    # state becomes RECONNECT_REQUIRED.
    assert _state(active=False, history=True, verified=False) == RECONNECT_REQUIRED


def test_revoked_history_is_reconnect_required():
    assert _state(active=False, history=True, verified=False) == RECONNECT_REQUIRED


def test_no_session_history_is_never_connected():
    assert _state(active=False, history=False, verified=False) == NOT_CONNECTED
    # Even a stray live observation cannot invent material that is not there.
    assert _state(active=False, history=False, verified=True) == NOT_CONNECTED


def test_the_four_accounts_do_not_share_state():
    tracker = ConnectionStateTracker()
    tracker.mark_authenticated(OUJDA)
    tracker.mark_authenticated(MAMDA_A)

    assert tracker.is_verified(OUJDA) is True
    assert tracker.is_verified(MAMDA_A) is True
    assert tracker.is_verified(NADOR) is False
    assert tracker.is_verified(MAMDA_B) is False

    tracker.mark_logged_out(OUJDA)
    # One account's logout says nothing about another's session.
    assert tracker.is_verified(OUJDA) is False
    assert tracker.is_verified(MAMDA_A) is True


def test_the_tracker_is_safe_to_read_while_the_poll_loop_writes():
    """The API reads this from worker threads while the poll loop writes
    from the event loop."""
    tracker = ConnectionStateTracker()
    errors: list[BaseException] = []
    stop = threading.Event()

    def writer():
        try:
            while not stop.is_set():
                tracker.mark_authenticated(OUJDA)
                tracker.mark_unverified(OUJDA)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    def reader():
        try:
            while not stop.is_set():
                tracker.is_verified(OUJDA)
                tracker.is_verified(NADOR)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=writer, daemon=True), threading.Thread(target=reader, daemon=True)]
    for thread in threads:
        thread.start()
    threading.Event().wait(0.3)
    stop.set()
    for thread in threads:
        thread.join(timeout=5)
    assert errors == []


def test_forgetting_an_account_only_forgets_that_one():
    tracker = ConnectionStateTracker()
    tracker.mark_authenticated(OUJDA)
    tracker.mark_authenticated(NADOR)
    tracker.forget(OUJDA)
    assert tracker.is_verified(OUJDA) is False
    assert tracker.is_verified(NADOR) is True
