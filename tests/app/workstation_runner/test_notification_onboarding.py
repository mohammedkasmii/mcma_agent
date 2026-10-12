"""mcma.app.workstation_runner.notification_onboarding -- the dedicated
lifecycle that claims a central notification-onboarding request, runs ONE
visible manual login, uploads the in-memory storage state once and cleans
up on every exit path. Pure unit tests: the client and the login are fakes,
no real HTTP/Playwright/Tk, no real sleeps (wait + tick are injected)."""

import asyncio
import logging
import threading
from dataclasses import dataclass

import pytest

from mcma.app.workstation_runner.browser_gate import (
    OWNER_JOB, OWNER_ONBOARDING, OWNER_SESSION, BrowserOperationGate,
)
from mcma.app.workstation_runner.http_client import (
    RegistryAccountBusy, RegistryClaimNotFound, RegistryConnectionError, RegistrySessionRejected,
    RegistryUnauthorized,
)
from mcma.app.workstation_runner.job_worker import JobPollingWorker
from mcma.app.workstation_runner.notification_onboarding import (
    NotificationOnboardingLifecycle, OnboardingEvent,
)

SECRET = "mcma_rs_" + "s" * 40
MARKER = "STORAGE-STATE-SECRET-MARKER"
STATE = {"cookies": [{"name": "sid", "value": MARKER}], "origins": []}


@dataclass(frozen=True)
class FakeClaim:
    account_id: str = "acct-mamda-oujda"
    request_id: str = "b" * 32
    generation: int = 3
    claim_token: str = "mcma_ot_" + "t" * 40
    lease_expires_at: str = "2026-01-01T00:01:00+00:00"
    expires_at: str = "2026-01-01T00:05:00+00:00"
    server_time: str = "2026-01-01T00:00:00+00:00"


@dataclass(frozen=True)
class Renewed:
    lease_expires_at: str = "t"
    server_time: str = "t"
    cancel_requested: bool = False


class FakeClient:
    def __init__(self, claims=()):
        self.claims = list(claims)
        self.claim_calls = 0
        self.renews: list = []
        self.completes: list = []
        self.fails: list = []
        self.closed = 0
        self.renew_behaviour = None       # callable(call_index) -> Renewed | raises
        self.complete_behaviour = None    # callable(call_index) -> None | raises
        self.claim_raises = None

    def claim_notification_onboarding(self, secret):
        self.claim_calls += 1
        if self.claim_raises is not None:
            raise self.claim_raises
        return self.claims.pop(0) if self.claims else None

    def renew_notification_onboarding(self, secret, *, request_id, claim_token, generation, phase):
        self.renews.append(phase)
        if self.renew_behaviour is not None:
            return self.renew_behaviour(len(self.renews) - 1)
        return Renewed()

    def complete_notification_onboarding(self, secret, *, request_id, claim_token, generation, storage_state):
        self.completes.append(storage_state)
        if self.complete_behaviour is not None:
            self.complete_behaviour(len(self.completes) - 1)
        return object()

    def fail_notification_onboarding(self, secret, *, request_id, claim_token, generation, reason_code):
        self.fails.append(reason_code)
        return object()

    def close(self):
        self.closed += 1


class FakeMaterial:
    def __init__(self, state):
        self._state = state
        self.consumed = 0

    def consume_for_handoff(self):
        self.consumed += 1
        return self._state


class FakeLogin:
    """perform_login double. `script` decides how the 'employee' behaves.
    Records window opens and browser closes (the finally of the real
    function) so cleanup-exactly-once is asserted."""

    def __init__(self, script="success"):
        self.script = script
        self.calls: list = []
        self.opened = 0
        self.closed = 0
        self.cancelled = 0
        self.release = None      # asyncio.Event created lazily on the loop
        self.material = FakeMaterial(STATE)
        self.timeouts: list = []

    async def __call__(self, account_id, on_window_opened, timeout_seconds):
        self.calls.append(account_id)
        self.timeouts.append(timeout_seconds)
        self.opened += 1
        try:
            on_window_opened()
            if self.script == "success":
                return self.material
            if self.script == "wait":
                await asyncio.Event().wait()      # until cancelled
            if isinstance(self.script, BaseException):
                raise self.script
            raise AssertionError("bad script")
        except asyncio.CancelledError:
            self.cancelled += 1
            raise
        finally:
            self.closed += 1


class Reasoned(Exception):
    def __init__(self, reason, text="portal said: hunter2"):
        super().__init__(text)
        self.reason = reason


def _lifecycle(client, login, *, gate=None, ready=True, events=None, **kwargs):
    events = events if events is not None else []
    kwargs.setdefault("renew_interval_seconds", 0.0)
    kwargs.setdefault("tick_seconds", 0.0)
    kwargs.setdefault("upload_retry_delay_seconds", 0.0)
    return NotificationOnboardingLifecycle(
        client, login, gate=gate or BrowserOperationGate(), is_ready=lambda: ready,
        on_event=events.append, wait=lambda event, timeout: event.is_set(), **kwargs,
    ), events


def _run_once(lifecycle, client, *, stop_after_first=True):
    """Runs the loop until the single queued claim has been handled."""
    stop = threading.Event()
    original = client.claim_notification_onboarding

    def claim(secret):
        result = original(secret)
        if result is None:
            stop.set()
        return result

    client.claim_notification_onboarding = claim
    lifecycle.run_forever(SECRET, stop)
    return stop


# ---------------------------------------------------------------- happy path ---------------------------------------------------------------- #


def test_success_claims_logs_in_uploads_once_and_cleans_up():
    client, login = FakeClient([FakeClaim()]), FakeLogin("success")
    gate = BrowserOperationGate()
    lifecycle, events = _lifecycle(client, login, gate=gate)
    _run_once(lifecycle, client)
    assert login.calls == ["acct-mamda-oujda"]            # a MAMDA notification account is accepted here
    assert login.material.consumed == 1                    # SessionMaterial's single consumption
    assert client.completes == [STATE] and client.fails == []
    assert login.closed == 1                               # browser/context closed exactly once
    assert OnboardingEvent.SUCCEEDED in events
    assert gate.holder() is None                           # gate released
    assert client.closed == 1


def test_phases_window_opened_then_waiting_for_login_while_login_runs():
    client, login = FakeClient([FakeClaim()]), FakeLogin("wait")

    def renew(i):
        if i >= 3:
            return Renewed(cancel_requested=True)       # end the wait deterministically
        return Renewed()

    client.renew_behaviour = renew
    lifecycle, _ = _lifecycle(client, login)
    _run_once(lifecycle, client)
    assert client.renews[:3] == ["OPENING_WINDOW", "WINDOW_OPENED", "WAITING_FOR_LOGIN"]


def test_login_timeout_is_bounded_by_server_deadline_not_by_a_server_supplied_host():
    claim = FakeClaim(server_time="2026-01-01T00:00:00+00:00", expires_at="2026-01-01T00:05:00+00:00")
    client, login = FakeClient([claim]), FakeLogin("success")
    lifecycle, _ = _lifecycle(client, login)
    _run_once(lifecycle, client)
    assert 0 < login.timeouts[0] <= 300


# ---------------------------------------------------------------- not claiming ---------------------------------------------------------------- #


def test_no_claim_while_not_ready_or_gate_busy():
    client, login = FakeClient([FakeClaim()]), FakeLogin()
    lifecycle, _ = _lifecycle(client, login, ready=False)
    stop = threading.Event()
    lifecycle._wait = lambda event, timeout: (stop.set() or True)
    lifecycle.run_forever(SECRET, stop)
    assert client.claim_calls == 0

    gate = BrowserOperationGate()
    assert gate.try_acquire(OWNER_SESSION)
    client2 = FakeClient([FakeClaim()])
    lifecycle2, _ = _lifecycle(client2, login, gate=gate)
    stop2 = threading.Event()
    lifecycle2._wait = lambda event, timeout: (stop2.set() or True)
    lifecycle2.run_forever(SECRET, stop2)
    assert client2.claim_calls == 0 and login.calls == []


def test_gate_is_exclusive_and_owner_checked():
    gate = BrowserOperationGate()
    assert gate.try_acquire(OWNER_JOB)
    assert not gate.try_acquire(OWNER_ONBOARDING)
    gate.release(OWNER_ONBOARDING)                          # not the holder: no-op
    assert gate.holder() == OWNER_JOB
    gate.release(OWNER_JOB)
    assert gate.try_acquire(OWNER_ONBOARDING)


def test_claim_failure_backs_off_without_a_browser():
    client, login = FakeClient(), FakeLogin()
    client.claim_raises = RegistryConnectionError("x")
    lifecycle, events = _lifecycle(client, login)
    stop = threading.Event()
    lifecycle._wait = lambda event, timeout: (stop.set() or True)
    lifecycle.run_forever(SECRET, stop)
    assert OnboardingEvent.CONNECTION_FAILED in events and login.calls == []


# ---------------------------------------------------------------- failures / cleanup ---------------------------------------------------------------- #


@pytest.mark.parametrize("exc,expected", [
    (Reasoned("LOGIN_TIMED_OUT"), "LOGIN_TIMED_OUT"),
    (Reasoned("LOGIN_WINDOW_CLOSED"), "LOGIN_WINDOW_CLOSED"),
    (Reasoned("LOGIN_PAGE_UNREACHABLE"), "LOGIN_PAGE_UNREACHABLE"),
    (Reasoned("SESSION_PROBE_FAILED_Boom"), "INTERNAL_ERROR"),
    (RuntimeError("secret detail hunter2"), "INTERNAL_ERROR"),
])
def test_login_failures_report_a_fixed_reason_and_close_the_browser_once(exc, expected):
    client, login = FakeClient([FakeClaim()]), FakeLogin(exc)
    lifecycle, events = _lifecycle(client, login)
    _run_once(lifecycle, client)
    assert client.fails == [expected] and client.completes == []
    assert login.closed == 1
    assert OnboardingEvent.FAILED in events


def test_server_cancel_request_cancels_login_and_reports_cancelled():
    client, login = FakeClient([FakeClaim()]), FakeLogin("wait")
    client.renew_behaviour = lambda i: Renewed(cancel_requested=True)
    lifecycle, events = _lifecycle(client, login)
    _run_once(lifecycle, client)
    assert login.cancelled == 1 and login.closed == 1
    assert client.fails == ["CANCELLED"] and client.completes == []
    assert OnboardingEvent.CANCELLED in events


def test_shutdown_during_login_cancels_it_and_reports_runner_shutdown():
    client, login = FakeClient([FakeClaim()]), FakeLogin("wait")
    stop = threading.Event()

    def renew(i):
        stop.set()
        return Renewed()

    client.renew_behaviour = renew
    lifecycle, _ = _lifecycle(client, login)
    lifecycle.run_forever(SECRET, stop)
    assert login.cancelled == 1 and login.closed == 1
    assert client.fails == ["RUNNER_SHUTDOWN"]


def test_shutdown_after_claim_never_opens_a_browser():
    client, login = FakeClient(), FakeLogin()
    stop = threading.Event()

    def claim(secret):
        stop.set()                         # shutdown lands between claim and launch
        return FakeClaim()

    client.claim_notification_onboarding = claim
    lifecycle, _ = _lifecycle(client, login)
    lifecycle.run_forever(SECRET, stop)
    assert login.calls == [] and login.opened == 0
    assert client.fails == ["RUNNER_SHUTDOWN"]


def test_lease_lost_on_renew_cancels_login_and_sends_nothing_further():
    client, login = FakeClient([FakeClaim()]), FakeLogin("wait")

    def renew(i):
        raise RegistryClaimNotFound()

    client.renew_behaviour = renew
    lifecycle, events = _lifecycle(client, login)
    _run_once(lifecycle, client)
    assert login.cancelled == 1 and login.closed == 1
    assert client.fails == [] and client.completes == []     # fenced: nothing more to say
    assert OnboardingEvent.LEASE_LOST in events


def test_unauthorized_on_renew_cancels_login():
    client, login = FakeClient([FakeClaim()]), FakeLogin("wait")

    def renew(i):
        raise RegistryUnauthorized("x")

    client.renew_behaviour = renew
    lifecycle, _ = _lifecycle(client, login)
    _run_once(lifecycle, client)
    assert login.cancelled == 1 and login.closed == 1


def test_repeated_renew_connection_failures_give_up_and_cancel_login():
    client, login = FakeClient([FakeClaim()]), FakeLogin("wait")

    def renew(i):
        raise RegistryConnectionError("x")

    client.renew_behaviour = renew
    lifecycle, _ = _lifecycle(client, login, max_renew_failures=3)
    _run_once(lifecycle, client)
    assert login.cancelled == 1 and login.closed == 1
    assert len(client.renews) == 3 and client.completes == []


# ---------------------------------------------------------------- upload ---------------------------------------------------------------- #


def test_upload_retries_account_busy_then_succeeds_with_same_state():
    client, login = FakeClient([FakeClaim()]), FakeLogin("success")

    def complete(i):
        if i < 2:
            raise RegistryAccountBusy()

    client.complete_behaviour = complete
    lifecycle, events = _lifecycle(client, login)
    _run_once(lifecycle, client)
    assert client.completes == [STATE, STATE, STATE] and client.fails == []
    assert OnboardingEvent.SUCCEEDED in events


def test_lost_response_connection_error_is_retried_idempotently():
    client, login = FakeClient([FakeClaim()]), FakeLogin("success")

    def complete(i):
        if i == 0:
            raise RegistryConnectionError("lost response")

    client.complete_behaviour = complete
    lifecycle, _ = _lifecycle(client, login)
    _run_once(lifecycle, client)
    assert len(client.completes) == 2 and client.fails == []


def test_upload_exhaustion_reports_upload_failed_and_does_not_loop_forever():
    client, login = FakeClient([FakeClaim()]), FakeLogin("success")

    def complete(i):
        raise RegistryAccountBusy()

    client.complete_behaviour = complete
    lifecycle, events = _lifecycle(client, login, upload_attempts=3)
    _run_once(lifecycle, client)
    assert len(client.completes) == 3 and client.fails == ["UPLOAD_FAILED"]
    assert OnboardingEvent.FAILED in events


def test_session_rejected_is_not_retried_and_not_failed_again():
    client, login = FakeClient([FakeClaim()]), FakeLogin("success")

    def complete(i):
        raise RegistrySessionRejected()

    client.complete_behaviour = complete
    lifecycle, events = _lifecycle(client, login)
    _run_once(lifecycle, client)
    assert len(client.completes) == 1 and client.fails == []
    assert OnboardingEvent.FAILED in events


def test_stale_claim_on_complete_stops_without_failing():
    client, login = FakeClient([FakeClaim()]), FakeLogin("success")

    def complete(i):
        raise RegistryClaimNotFound()

    client.complete_behaviour = complete
    lifecycle, events = _lifecycle(client, login)
    _run_once(lifecycle, client)
    assert len(client.completes) == 1 and client.fails == []
    assert OnboardingEvent.LEASE_LOST in events


def test_shutdown_during_upload_retries_stops_retrying():
    client, login = FakeClient([FakeClaim()]), FakeLogin("success")
    stop = threading.Event()

    def complete(i):
        stop.set()
        raise RegistryAccountBusy()

    client.complete_behaviour = complete
    lifecycle, _ = _lifecycle(client, login)
    lifecycle.run_forever(SECRET, stop)
    assert len(client.completes) == 1


# ---------------------------------------------------------------- safety ---------------------------------------------------------------- #


def test_no_storage_marker_or_exception_text_in_logs_or_events(caplog):
    caplog.set_level(logging.DEBUG)
    client, login = FakeClient([FakeClaim()]), FakeLogin("success")

    def complete(i):
        raise RegistryConnectionError(f"leaky {MARKER}")

    client.complete_behaviour = complete
    lifecycle, events = _lifecycle(client, login, upload_attempts=2)
    _run_once(lifecycle, client)
    blob = " ".join(r.getMessage() for r in caplog.records) + " ".join(repr(e) for e in events)
    assert MARKER not in blob and "hunter2" not in blob and "mcma_ot_" not in blob


def test_worker_module_never_imports_the_dpapi_store_playwright_portal_or_tk():
    import ast

    import mcma.app.workstation_runner.notification_onboarding as module
    tree = ast.parse(open(module.__file__, encoding="utf-8").read())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
            imported.update(f"{node.module}.{a.name}" for a in node.names)
    for forbidden in ("session_store", "playwright", "tkinter", "mcma.portal", "sqlite3", "fastapi"):
        assert not any(forbidden in name for name in imported), forbidden


def test_gate_released_even_when_the_driver_itself_crashes():
    client, login = FakeClient([FakeClaim()]), FakeLogin("wait")
    gate = BrowserOperationGate()

    class Boom(BaseException):
        pass

    def renew(i):
        raise Boom()

    client.renew_behaviour = renew
    lifecycle, _ = _lifecycle(client, login, gate=gate)
    with pytest.raises(Boom):
        _run_once(lifecycle, client)
    assert login.closed == 1 and gate.holder() is None


# ---------------------------------------------------------------- thread wrapper ---------------------------------------------------------------- #


def test_worker_wrapper_never_starts_or_resurrects_after_stop():
    client, login = FakeClient(), FakeLogin()
    lifecycle, _ = _lifecycle(client, login)
    worker = JobPollingWorker(lifecycle, SECRET)
    assert worker.stop(timeout=1.0)
    worker.start()                      # a stopped worker is never resurrected
    assert not worker.is_alive() and client.claim_calls == 0


def test_worker_wrapper_runs_one_thread_and_stops_cleanly():
    client, login = FakeClient(), FakeLogin()
    lifecycle = NotificationOnboardingLifecycle(
        client, login, gate=BrowserOperationGate(), is_ready=lambda: True, on_event=lambda e: None,
        poll_interval_seconds=0.01,
    )
    worker = JobPollingWorker(lifecycle, SECRET)
    worker.start()
    worker.start()
    assert worker.stop(timeout=3.0)
    assert not worker.is_alive()
    assert client.closed == 1


# ------------------------------------------------ lease kept through opening and upload ------------------------------------------------ #

from mcma.app.workstation_runner import http_client as _http_client  # noqa: E402


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class SlowOpenLogin(FakeLogin):
    """The Chromium/login-page startup is slow: the window only 'opens' once
    `open_gate` is set (by a renew, i.e. after simulated time has passed).
    Spins on sleep(0): no real sleeping."""

    def __init__(self, material_script="success"):
        super().__init__(material_script)
        self.open_gate = threading.Event()

    async def __call__(self, account_id, on_window_opened, timeout_seconds):
        self.calls.append(account_id)
        self.timeouts.append(timeout_seconds)
        try:
            while not self.open_gate.is_set():
                await asyncio.sleep(0)
            on_window_opened()
            return self.material
        except asyncio.CancelledError:
            self.cancelled += 1
            raise
        finally:
            self.closed += 1


def _run_with(lifecycle, client, stop):
    original = client.claim_notification_onboarding

    def claim(secret):
        result = original(secret)
        if result is None:
            stop.set()
        return result

    client.claim_notification_onboarding = claim
    lifecycle.run_forever(SECRET, stop)


def test_lease_arithmetic_is_strictly_inside_the_server_ttl():
    from mcma.app.workstation_runner import notification_onboarding as module

    max_call = (_http_client._CONNECT_TIMEOUT + _http_client._WRITE_TIMEOUT
                + _http_client._READ_TIMEOUT + _http_client._POOL_TIMEOUT)
    assert max_call < module._LEASE_TTL_SECONDS
    assert module._DEFAULT_RENEW_INTERVAL_SECONDS + max_call < module._LEASE_TTL_SECONDS
    # hard deadline 420 s - upload reserve leaves a login window of at most 300 s
    claim = FakeClaim(server_time="2026-01-01T00:00:00+00:00", expires_at="2026-01-01T00:07:00+00:00")
    lifecycle, _ = _lifecycle(FakeClient(), FakeLogin())
    assert lifecycle._login_timeout(claim) == 300.0
    short = FakeClaim(server_time="2026-01-01T00:00:00+00:00", expires_at="2026-01-01T00:02:00+00:00")
    assert lifecycle._login_timeout(short) == 45.0


def test_renewals_continue_while_the_browser_opens_longer_than_one_lease_ttl():
    clock, client, login = FakeClock(), FakeClient([FakeClaim()]), SlowOpenLogin()

    def renew(i):
        clock.advance(20.0)                    # 20 s per renew: 4 renews = 80 s > the 60 s lease TTL
        if i == 3:
            login.open_gate.set()
        return Renewed()

    client.renew_behaviour = renew
    lifecycle, events = _lifecycle(client, login, clock=clock)
    _run_once(lifecycle, client)
    assert client.renews[:4] == ["OPENING_WINDOW"] * 4
    assert clock.now - 1000.0 >= 80.0
    assert OnboardingEvent.LEASE_LOST not in events and OnboardingEvent.SUCCEEDED in events
    assert client.completes == [STATE] and login.closed == 1


def test_cancellation_during_opening_closes_the_browser_and_never_completes():
    client, login = FakeClient([FakeClaim()]), SlowOpenLogin()
    client.renew_behaviour = lambda i: Renewed(cancel_requested=(i >= 1))
    lifecycle, events = _lifecycle(client, login)
    _run_once(lifecycle, client)
    assert client.fails == ["CANCELLED"] and client.completes == []
    assert login.closed == 1 and login.cancelled == 1 and OnboardingEvent.CANCELLED in events


def test_shutdown_during_opening_closes_the_browser_exactly_once():
    client, login, stop = FakeClient([FakeClaim()]), SlowOpenLogin(), threading.Event()

    def renew(i):
        stop.set()
        return Renewed()

    client.renew_behaviour = renew
    lifecycle, _ = _lifecycle(client, login)
    _run_with(lifecycle, client, stop)
    assert login.closed == 1 and client.fails == ["RUNNER_SHUTDOWN"] and client.completes == []


def test_slow_retried_upload_keeps_renewing_and_never_loses_the_lease():
    clock, client, login = FakeClock(), FakeClient([FakeClaim()]), FakeLogin("success")

    def complete(i):
        clock.advance(25.0)                    # a call that ran into its full 25 s timeout
        if i < 2:
            raise RegistryConnectionError()

    client.complete_behaviour = complete
    lifecycle, events = _lifecycle(client, login, clock=clock, renew_interval_seconds=15.0)
    _run_once(lifecycle, client)
    assert client.completes == [STATE] * 3      # same state each time: idempotent retry
    upload_renews = client.renews[1:]           # [0] is the drive-loop renew
    assert len(upload_renews) >= 3 and set(upload_renews) == {"WAITING_FOR_LOGIN"}
    assert OnboardingEvent.LEASE_LOST not in events and OnboardingEvent.SUCCEEDED in events


def test_cancellation_seen_just_before_upload_prevents_complete():
    client, login = FakeClient([FakeClaim()]), FakeLogin("success")
    client.renew_behaviour = lambda i: Renewed(cancel_requested=(i >= 1))   # drive renew clean, pre-upload renew cancels
    lifecycle, events = _lifecycle(client, login)
    _run_once(lifecycle, client)
    assert client.completes == [] and client.fails == ["CANCELLED"]
    assert login.material.consumed == 1 and login.closed == 1 and OnboardingEvent.CANCELLED in events


def test_hard_deadline_reached_before_upload_fences_the_stale_claim():
    clock, client, login = FakeClock(), FakeClient([FakeClaim()]), FakeLogin("success")

    def renew(i):
        clock.advance(421.0)                   # beyond expires_at - server_time; the server has fenced the request
        return Renewed()

    client.renew_behaviour = renew
    lifecycle, events = _lifecycle(client, login, clock=clock)
    _run_once(lifecycle, client)
    assert client.completes == [] and OnboardingEvent.LEASE_LOST in events and client.fails == []


def test_lease_lapse_during_upload_stops_retrying_complete():
    clock, client, login = FakeClock(), FakeClient([FakeClaim()]), FakeLogin("success")

    def renew(i):
        if i >= 1:
            clock.advance(61.0)                # the pre-upload renew fails and the lease TTL has passed
            raise RegistryConnectionError()
        return Renewed()

    client.renew_behaviour = renew
    lifecycle, events = _lifecycle(client, login, clock=clock)
    _run_once(lifecycle, client)
    assert client.completes == [] and OnboardingEvent.LEASE_LOST in events
