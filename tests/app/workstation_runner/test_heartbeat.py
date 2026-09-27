import threading

import pytest

from mcma.app.workstation_runner.heartbeat import HeartbeatLifecycle, HeartbeatWorker, LifecycleEvent
from mcma.app.workstation_runner.http_client import HeartbeatResult, RegistryConnectionError, RegistryUnauthorized
from tests.app.workstation_runner._fakes import FakeStopWaiter

SECRET = "mcma_rs_" + "s" * 40


class _ScriptedClient:
    def __init__(self, outcomes):
        self._outcomes = list(outcomes)
        self.calls = 0
        self.closed = False

    def heartbeat(self, runner_secret, *, sessions=()):
        self.calls += 1
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def close(self):
        self.closed = True


def _ok(interval=10, offline=30):
    return HeartbeatResult(status="ACTIVE", heartbeat_interval_seconds=interval, offline_after_seconds=offline, allowed_account_ids=())


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


def test_heartbeat_always_sends_the_sessions_it_was_given_never_a_cached_account_list():
    """RELEASE BLOCKER 3: the loop must forward exactly the `sessions` it
    was started with on every call -- it must never derive, cache, or
    resend an account-list "authorization claim" of its own. Phase 1B-A
    always passes the default empty sessions; this proves the loop itself
    adds nothing on top."""
    client = _ScriptedClient([_ok(), _ok()])
    waiter = FakeStopWaiter()
    waiter.stop_after(1)
    seen = []
    original_heartbeat = client.heartbeat

    def recording_heartbeat(runner_secret, *, sessions=()):
        seen.append(sessions)
        return original_heartbeat(runner_secret, sessions=sessions)

    client.heartbeat = recording_heartbeat
    HeartbeatLifecycle(client, lambda e: None, wait=waiter).run_once_loop(SECRET, threading.Event())
    assert seen == [(), ()]


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


def test_worker_forwards_sessions_to_the_lifecycle():
    received = {}

    class _RecordingLifecycle:
        def run_once_loop(self, secret, stop_event, *, sessions=()):
            received["sessions"] = sessions

    sessions = ({"account_id": "acct-mcma-oujda", "state": "READY"},)
    worker = HeartbeatWorker(_RecordingLifecycle(), SECRET, sessions=sessions)
    worker.start()
    worker.stop(timeout=2)
    assert received["sessions"] == sessions
