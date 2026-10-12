"""RunnerController integration of the notification-onboarding worker:
started only after pairing/heartbeat identity exists, never without a
factory, stopped on shutdown, claims only while connected (NOT gated on
MCMA agent-session readiness -- MAMDA-only employees may onboard), and
the saved-session login refuses while an onboarding window owns the
browser."""

import threading

from mcma.app.workstation_runner.browser_gate import OWNER_ONBOARDING, BrowserOperationGate
from mcma.app.workstation_runner.notification_onboarding import OnboardingEvent

from tests.app.workstation_runner.test_controller import (
    _FakeBrowserWorker, _FakeClient, _FakeIdentityStore, _NullLifecycle, _ShutdownGuard, _config, _new_controller,
    _paired_controller, _wait_until,
)


class _RecordingOnboardingLifecycle:
    def __init__(self):
        self.run_calls: list = []

    def run_forever(self, secret, stop_event):
        self.run_calls.append(secret)
        stop_event.wait()


def test_onboarding_worker_starts_after_pairing_on_its_own_client():
    lifecycle = _RecordingOnboardingLifecycle()
    clients = []

    controller, store = _paired_controller(
        onboarding_lifecycle_factory=lambda client: clients.append(client) or lifecycle,
    )
    with _ShutdownGuard(controller):
        controller.start()
        controller.submit_pairing("mcma_pc_x")
        assert _wait_until(lambda: len(lifecycle.run_calls) == 1)
        assert lifecycle.run_calls == [store.saved.runner_secret]
        assert len(clients) == 1


def test_no_onboarding_worker_without_a_factory():
    controller, store = _paired_controller()
    with _ShutdownGuard(controller):
        controller.start()
        controller.submit_pairing("mcma_pc_x")
        assert _wait_until(lambda: store.saved is not None)
        assert controller._onboarding_worker is None


def test_shutdown_stops_the_onboarding_worker():
    lifecycle = _RecordingOnboardingLifecycle()
    controller, _ = _paired_controller(onboarding_lifecycle_factory=lambda client: lifecycle)
    controller.start()
    controller.submit_pairing("mcma_pc_x")
    assert _wait_until(lambda: len(lifecycle.run_calls) == 1)
    assert controller.shutdown(timeout=2.0) is True
    assert not controller._onboarding_worker.is_alive()


def test_no_onboarding_worker_is_started_once_shutdown_began():
    lifecycle = _RecordingOnboardingLifecycle()
    controller, store = _paired_controller(onboarding_lifecycle_factory=lambda client: lifecycle)
    assert controller.shutdown(timeout=1.0) is True
    controller.submit_pairing("mcma_pc_x")
    controller._start_onboarding_worker("mcma_rs_" + "c" * 40)
    assert lifecycle.run_calls == [] and controller._onboarding_worker is None


def test_onboarding_ready_needs_connection_but_not_an_mcma_ready_account():
    controller = _new_controller()
    assert controller._onboarding_is_ready() is False
    controller._connected.set()
    assert controller._onboarding_is_ready() is True       # no READY MCMA session required
    controller._closing.set()
    assert controller._onboarding_is_ready() is False


def test_saved_session_login_is_refused_while_onboarding_owns_the_browser():
    gate = BrowserOperationGate()
    worker = _FakeBrowserWorker()
    controller = _new_controller(browser_worker=worker, gate=gate)
    assert gate.try_acquire(OWNER_ONBOARDING)
    assert controller.request_login("acct-mcma-oujda") is False
    assert worker.login_requests == []
    gate.release(OWNER_ONBOARDING)
    assert controller.request_login("acct-mcma-oujda") is True


def test_onboarding_events_are_logged_as_fixed_names_only():
    logs = []
    controller = _new_controller(on_log=logs.append)
    for event in OnboardingEvent:
        controller._handle_onboarding_event(event)
    assert logs and all(name.startswith("notification_onboarding_") for name in logs)
    assert all(" " not in name for name in logs)
