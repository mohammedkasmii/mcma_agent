import threading

import pytest

from mcma.app.workstation_runner.heartbeat import HeartbeatLifecycle, HeartbeatWorker, LifecycleEvent
from mcma.app.workstation_runner.http_client import (
    HeartbeatResult, RegistryAccountNotAllowed, RegistryConnectionError, RegistryUnauthorized,
)
from tests.app.workstation_runner._fakes import FakeStopWaiter

SECRET = "mcma_rs_" + "s" * 40


class _ScriptedClient:
    def __init__(self, outcomes):
        self._outcomes = list(outcomes)
        self.calls = 0
        self.closed = False
        self.sessions_seen = []

    def heartbeat(self, runner_secret, *, sessions=()):
        self.calls += 1
        self.sessions_seen.append(sessions)
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def close(self):
        self.closed = True


def _ok(interval=10, offline=30, allowed_account_ids=()):
    return HeartbeatResult(
        status="ACTIVE", heartbeat_interval_seconds=interval, offline_after_seconds=offline,
        allowed_account_ids=allowed_account_ids,
    )


def test_first_heartbeat_is_sent_immediately_without_waiting():
    client = _ScriptedClient([_ok()])
    waiter = FakeStopWaiter()
    waiter.stop_on_next_wait()  # stop as soon as the loop waits after the first success
    events = []
    lifecycle = HeartbeatLifecycle(client, events.append, wait=waiter)
    lifecycle.run_once_loop(SECRET, threading.Event())
    assert client.calls == 1
    assert events == [LifecycleEvent.CONNECTED]


def test_success_waits_for_server_provided_interval():
    client = _ScriptedClient([_ok(interval=42)])
    waiter = FakeStopWaiter()
    waiter.stop_on_next_wait()
    HeartbeatLifecycle(client, lambda e: None, wait=waiter).run_once_loop(SECRET, threading.Event())
    assert waiter.waits == [42]


@pytest.mark.parametrize("bad_interval", [0, -1, 999999])
def test_out_of_bounds_interval_falls_back_to_a_safe_default(bad_interval):
    client = _ScriptedClient([_ok(interval=bad_interval)])
    waiter = FakeStopWaiter()
    waiter.stop_on_next_wait()
    HeartbeatLifecycle(client, lambda e: None, wait=waiter).run_once_loop(SECRET, threading.Event())
    assert 1 <= waiter.waits[0] <= 3600


def test_connection_failure_backs_off_and_retries_then_recovers():
    client = _ScriptedClient([RegistryConnectionError("x"), RegistryConnectionError("x"), _ok()])
    waiter = FakeStopWaiter()
    waiter.stop_after(2)  # stop during the wait after the 3rd call succeeds
    events = []
    HeartbeatLifecycle(client, events.append, wait=waiter).run_once_loop(SECRET, threading.Event())
    assert client.calls == 3
    assert events == [LifecycleEvent.CONNECTION_FAILED, LifecycleEvent.CONNECTION_FAILED, LifecycleEvent.CONNECTED]
    assert waiter.waits[0] >= 1 and waiter.waits[1] >= waiter.waits[0]  # never a tight loop, backs off


def test_heartbeat_sends_no_sessions_by_default_never_a_cached_account_list():
    """RELEASE BLOCKER 3: with no sessions_provider given, the loop must
    never derive, cache, or resend an account-list "authorization claim"
    of its own -- the default sessions_provider is a fixed empty tuple."""
    client = _ScriptedClient([_ok(), _ok()])
    waiter = FakeStopWaiter()
    waiter.stop_after(1)
    HeartbeatLifecycle(client, lambda e: None, wait=waiter).run_once_loop(SECRET, threading.Event())
    assert client.sessions_seen == [(), ()]


def test_sessions_provider_is_called_fresh_on_every_iteration_never_cached():
    """The provider's RETURN VALUE, not a snapshot taken once at
    construction, is what each heartbeat call sends -- a change between
    iterations (exactly what WorkstationSessionManager.heartbeat_sessions()
    reflects as real state changes) must be visible on the very next call."""
    client = _ScriptedClient([_ok(), _ok(), _ok()])
    waiter = FakeStopWaiter()
    waiter.stop_after(2)
    call_count = 0

    def sessions_provider():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return ()
        return ({"account_id": "acct-mcma-oujda", "state": "READY"},)

    HeartbeatLifecycle(
        client, lambda e: None, wait=waiter, sessions_provider=sessions_provider,
    ).run_once_loop(SECRET, threading.Event())
    assert client.sessions_seen == [
        (), ({"account_id": "acct-mcma-oujda", "state": "READY"},),
        ({"account_id": "acct-mcma-oujda", "state": "READY"},),
    ]
    assert call_count == 3  # once per iteration, never memoized


def test_on_allowed_accounts_is_called_after_every_successful_heartbeat():
    client = _ScriptedClient([
        _ok(allowed_account_ids=("acct-mcma-oujda",)),
        _ok(allowed_account_ids=("acct-mcma-oujda", "acct-mcma-nador")),
    ])
    waiter = FakeStopWaiter()
    waiter.stop_after(1)
    seen = []
    HeartbeatLifecycle(
        client, lambda e: None, wait=waiter, on_allowed_accounts=seen.append,
    ).run_once_loop(SECRET, threading.Event())
    assert seen == [("acct-mcma-oujda",), ("acct-mcma-oujda", "acct-mcma-nador")]


def test_account_not_allowed_retries_exactly_once_with_empty_sessions_then_reconciles():
    client = _ScriptedClient([
        RegistryAccountNotAllowed(), _ok(allowed_account_ids=("acct-mcma-oujda",)),
    ])
    waiter = FakeStopWaiter()
    waiter.stop_on_next_wait()
    seen_accounts = []
    HeartbeatLifecycle(
        client, lambda e: None, wait=waiter,
        sessions_provider=lambda: ({"account_id": "acct-mcma-oujda", "state": "READY"},),
        on_allowed_accounts=seen_accounts.append,
    ).run_once_loop(SECRET, threading.Event())
    assert client.calls == 2
    # the FIRST call used the real (stale) sessions claim; the retry used
    # an empty one, never the response body, never a second retry.
    assert client.sessions_seen == [({"account_id": "acct-mcma-oujda", "state": "READY"},), ()]
    assert seen_accounts == [("acct-mcma-oujda",)]  # reconciled from the retry's own result


def test_account_not_allowed_does_not_create_an_unbounded_retry_loop():
    """If the empty-session retry ALSO fails, normal connection/protocol
    failure behavior applies -- never a second retry."""
    client = _ScriptedClient([RegistryAccountNotAllowed(), RegistryAccountNotAllowed()])
    waiter = FakeStopWaiter()
    waiter.stop_on_next_wait()
    events = []
    HeartbeatLifecycle(client, events.append, wait=waiter).run_once_loop(SECRET, threading.Event())
    assert client.calls == 2  # exactly one retry -- not a second one
    assert events == [LifecycleEvent.CONNECTION_FAILED]


def test_account_not_allowed_retry_that_hits_unauthorized_reports_unauthorized():
    client = _ScriptedClient([RegistryAccountNotAllowed(), RegistryUnauthorized("x")])
    events = []
    HeartbeatLifecycle(client, events.append, wait=FakeStopWaiter()).run_once_loop(SECRET, threading.Event())
    assert client.calls == 2
    assert events == [LifecycleEvent.UNAUTHORIZED]


def test_client_is_closed_after_a_normal_stop():
    client = _ScriptedClient([_ok()])
    waiter = FakeStopWaiter()
    waiter.stop_on_next_wait()
    HeartbeatLifecycle(client, lambda e: None, wait=waiter).run_once_loop(SECRET, threading.Event())
    assert client.closed is True


def test_client_is_closed_after_unauthorized():
    client = _ScriptedClient([RegistryUnauthorized("x")])
    HeartbeatLifecycle(client, lambda e: None, wait=FakeStopWaiter()).run_once_loop(SECRET, threading.Event())
    assert client.closed is True


def test_unauthorized_is_reported_but_lifecycle_never_touches_identity_store():
    """CLEANUP: HeartbeatLifecycle no longer accepts or clears an
    identity_store at all -- the controller is the sole owner of that
    decision (see RunnerController._handle_lifecycle_event)."""
    client = _ScriptedClient([RegistryUnauthorized("x")])
    waiter = FakeStopWaiter()
    events = []
    HeartbeatLifecycle(client, events.append, wait=waiter).run_once_loop(SECRET, threading.Event())
    assert events == [LifecycleEvent.UNAUTHORIZED]
    assert client.calls == 1
    assert waiter.waits == []  # returns immediately, no further waiting/looping


def test_stop_event_set_before_loop_starts_sends_no_heartbeat():
    client = _ScriptedClient([])
    stop = threading.Event()
    stop.set()
    HeartbeatLifecycle(client, lambda e: None, wait=FakeStopWaiter()).run_once_loop(SECRET, stop)
    assert client.calls == 0
    assert client.closed is True  # still closed even though no heartbeat was ever sent


def test_worker_stop_before_start_never_raises():
    """A HeartbeatWorker whose start() has not been called yet (or has not
    finished) must never crash stop() with Thread.join()'s "cannot join
    thread before it is started" -- self._thread stays None until start()
    has actually launched the OS thread."""
    worker = HeartbeatWorker(lifecycle=None, runner_secret=SECRET)
    worker.stop(timeout=1)  # must not raise
    assert not worker.is_alive()


def test_worker_start_and_bounded_stop_join():
    started = threading.Event()

    class _BlockingLifecycle:
        def run_once_loop(self, secret, stop_event, *, sessions=()):
            started.set()
            stop_event.wait(5)

    worker = HeartbeatWorker(_BlockingLifecycle(), SECRET)
    worker.start()
    assert started.wait(1)
    worker.stop(timeout=2)
    assert not worker.is_alive()


def test_worker_calls_run_once_loop_with_no_sessions_kwarg():
    """Sessions are now the LIFECYCLE's own concern (sessions_provider,
    called fresh every iteration) -- HeartbeatWorker itself no longer
    threads a static sessions value through at all."""
    received = {}

    class _RecordingLifecycle:
        def run_once_loop(self, secret, stop_event):
            received["called"] = True

    worker = HeartbeatWorker(_RecordingLifecycle(), SECRET)
    worker.start()
    worker.stop(timeout=2)
    assert received["called"] is True
