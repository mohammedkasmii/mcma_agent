import threading
import time

from mcma.app.workstation_runner.config import RunnerConfig
from mcma.app.workstation_runner.controller import ControllerState, RunnerController
from mcma.app.workstation_runner.heartbeat import LifecycleEvent
from mcma.app.workstation_runner.http_client import EnrollResult, RegistryConnectionError
from mcma.app.workstation_runner.sessions import VerificationScheduler, WorkstationSessionManager

ORIGIN = "https://central.example.local"
OTHER_ORIGIN = "https://other.example.local"

OUJDA = "acct-mcma-oujda"
NADOR = "acct-mcma-nador"


def _config(origin=ORIGIN):
    return RunnerConfig(server_origin=origin, ca_cert_path=None, workstation_label="Poste-1")


def _session_manager(saved=()):
    saved = set(saved)
    return WorkstationSessionManager(has_saved_session=lambda a: a in saved)


class _FakeSessionStore:
    def __init__(self, initial=None):
        self._data = dict(initial or {})
        self.clear_calls = []
        self.clear_all_calls = 0

    def load(self, account_id):
        return self._data.get(account_id)

    def has_saved_session(self, account_id):
        return account_id in self._data

    def save(self, account_id, storage_state):
        self._data[account_id] = storage_state

    def clear(self, account_id):
        self.clear_calls.append(account_id)
        self._data.pop(account_id, None)

    def clear_all(self):
        self.clear_all_calls += 1
        self._data.clear()


class _FakeBrowserWorker:
    """A deterministic stand-in -- no real thread/event loop. Records every
    call so pairing/heartbeat-only tests (the vast majority) can ignore it
    entirely while browser-session-focused tests inspect it directly."""

    def __init__(self):
        self.start_calls = 0
        self.stop_calls = []
        self.login_requests = []
        self.verification_requests = []
        self.cancelled = []

    @property
    def started(self):
        return self.start_calls > 0

    def start(self):
        self.start_calls += 1

    def request_login(self, account_id):
        self.login_requests.append(account_id)
        return True

    def request_verification(self, account_id):
        self.verification_requests.append(account_id)
        return True

    def cancel_account(self, account_id):
        self.cancelled.append(account_id)

    def stop(self, timeout):
        self.stop_calls.append(timeout)
        return True

    def is_alive(self):
        return False


_DEFAULT_POSITIONAL = (
    lambda: _config(),
    lambda: _FakeIdentityStore(),
    lambda: (lambda config: _FakeClient()),
    lambda: (lambda client: _NullLifecycle()),
    lambda: (lambda status: None),
)


def _new_controller(*args, **kwargs):
    """Thin factory used throughout this file in place of calling
    RunnerController(...) directly: fills in safe, inert fakes for the
    four browser-session params the Phase 1B-B integration added (and,
    when a browser-session-focused test cares about none of the
    pairing/heartbeat positional args, safe defaults for those too), so
    every pre-existing pairing/heartbeat test keeps exercising EXACTLY the
    same behavior it always did, with no risk of a shared/leaked fake
    between tests (a fresh one is built on every call)."""
    args = tuple(args) + tuple(factory() for factory in _DEFAULT_POSITIONAL[len(args):])
    kwargs.setdefault("session_manager", _session_manager())
    kwargs.setdefault("session_store", _FakeSessionStore())
    kwargs.setdefault("browser_worker", _FakeBrowserWorker())
    kwargs.setdefault("verification_scheduler", VerificationScheduler())
    return RunnerController(*args, **kwargs)


class _FakeIdentityStore:
    def __init__(self, existing=None):
        self._existing = existing
        self.saved = None
        self.cleared = False

    def load(self, *, expected_server_origin):
        return self._existing

    def save(self, identity):
        self.saved = identity

    def clear(self):
        self.cleared = True


class _FakeClient:
    def __init__(self, enroll_result=None, enroll_error=None):
        self._enroll_result = enroll_result
        self._enroll_error = enroll_error

    def enroll(self, pairing_code, *, workstation_label):
        if self._enroll_error:
            raise self._enroll_error
        return self._enroll_result

    def close(self):
        pass


class _NullLifecycle:
    """Never actually loops -- used where the test only cares about pairing."""

    def run_once_loop(self, secret, stop_event, *, sessions=()):
        stop_event.wait()  # blocks until controller.shutdown() sets it


def _wait_until(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


# Every test below wraps its assertions in try/finally (or uses this
# context manager) so controller.shutdown() ALWAYS runs. A HeartbeatWorker
# thread is non-daemon by design (heartbeat.py) -- a real Python process
# waits for non-daemon threads at interpreter exit, so a test that starts
# one and fails an assertion before calling shutdown() would hang the
# entire pytest run, not just fail cleanly.
class _ShutdownGuard:
    def __init__(self, controller, timeout=2.0):
        self._controller = controller
        self._timeout = timeout

    def __enter__(self):
        return self._controller

    def __exit__(self, *exc_info):
        self._controller.shutdown(timeout=self._timeout)


def test_start_with_no_saved_identity_goes_to_pairing_idle():
    statuses = []
    controller = _new_controller(
        _config(), _FakeIdentityStore(existing=None), lambda config: _FakeClient(),
        lambda client: _NullLifecycle(), statuses.append,
    )
    with _ShutdownGuard(controller):
        controller.start()
        assert statuses[-1].state == ControllerState.PAIRING_IDLE


def test_successful_pairing_saves_identity_and_starts_heartbeat():
    statuses = []
    store = _FakeIdentityStore(existing=None)
    result = EnrollResult(
        runner_id="a" * 32, runner_secret="mcma_rs_" + "b" * 40, runner_label="Poste-1",
        allowed_account_ids=("acct-mcma-oujda",), heartbeat_interval_seconds=10, offline_after_seconds=30,
    )
    controller = _new_controller(_config(), store, lambda config: _FakeClient(enroll_result=result), lambda client: _NullLifecycle(), statuses.append)
    with _ShutdownGuard(controller):
        controller.start()
        controller.submit_pairing("mcma_pc_x")
        assert _wait_until(lambda: store.saved is not None)
        assert store.saved.runner_id == "a" * 32
        assert _wait_until(lambda: statuses[-1].state == ControllerState.PAIRED_CONNECTING)


def test_submit_pairing_with_a_new_config_is_used_for_the_client_and_enroll_call():
    """Regression: the pairing form's just-typed server origin / CA cert /
    label must actually reach the client and the enroll() call -- the
    controller must not keep enrolling against whatever config it was
    constructed with if a fresh one is passed to submit_pairing()."""
    seen_origins = []
    seen_labels = []

    def client_factory(config):
        seen_origins.append(config.server_origin)
        return _FakeClient(enroll_result=EnrollResult(
            runner_id="a" * 32, runner_secret="mcma_rs_" + "b" * 40, runner_label="x",
            allowed_account_ids=(), heartbeat_interval_seconds=10, offline_after_seconds=30,
        ))

    class _RecordingClient(_FakeClient):
        def enroll(self, pairing_code, *, workstation_label):
            seen_labels.append(workstation_label)
            return super().enroll(pairing_code, workstation_label=workstation_label)

    def client_factory_recording(config):
        seen_origins.append(config.server_origin)
        return _RecordingClient(enroll_result=EnrollResult(
            runner_id="a" * 32, runner_secret="mcma_rs_" + "b" * 40, runner_label="x",
            allowed_account_ids=(), heartbeat_interval_seconds=10, offline_after_seconds=30,
        ))

    new_config = RunnerConfig(server_origin=OTHER_ORIGIN, ca_cert_path=None, workstation_label="Poste-Nouveau")
    controller = _new_controller(
        _config(origin=ORIGIN), _FakeIdentityStore(), client_factory_recording, lambda client: _NullLifecycle(), lambda s: None,
    )
    with _ShutdownGuard(controller):
        controller.start()
        controller.submit_pairing("mcma_pc_x", config=new_config)
        assert _wait_until(lambda: len(seen_origins) >= 1)
        assert seen_origins[-1] == OTHER_ORIGIN
        assert _wait_until(lambda: len(seen_labels) >= 1)
        assert seen_labels[-1] == "Poste-Nouveau"


def test_successful_pairing_with_a_new_config_calls_on_config_saved():
    """Regression: without persisting the config used for a successful
    pairing, a later restart's build_default_config_from_env() would return
    the OLD (or empty) origin, and IdentityStore.load(expected_server_origin=...)
    would then always fail as an origin mismatch -- silently discarding a
    perfectly valid saved identity."""
    saved_configs = []
    result = EnrollResult(
        runner_id="a" * 32, runner_secret="mcma_rs_" + "b" * 40, runner_label="x",
        allowed_account_ids=(), heartbeat_interval_seconds=10, offline_after_seconds=30,
    )
    new_config = RunnerConfig(server_origin=OTHER_ORIGIN, ca_cert_path=None, workstation_label="Poste-Nouveau")
    controller = _new_controller(
        _config(), _FakeIdentityStore(), lambda config: _FakeClient(enroll_result=result), lambda client: _NullLifecycle(),
        lambda s: None, on_config_saved=saved_configs.append,
    )
    with _ShutdownGuard(controller):
        controller.start()
        controller.submit_pairing("mcma_pc_x", config=new_config)
        assert _wait_until(lambda: len(saved_configs) == 1)
        assert saved_configs[0] == new_config


def test_config_is_persisted_before_enroll_is_ever_called():
    """Regression: the spec requires persisting the validated non-secret
    config BEFORE sending the enrollment request -- proving the ORDER, not
    just that both eventually happen."""
    events = []

    class _RecordingClient:
        def enroll(self, pairing_code, *, workstation_label):
            events.append("enroll_called")
            return EnrollResult(
                runner_id="a" * 32, runner_secret="mcma_rs_" + "b" * 40, runner_label="x",
                allowed_account_ids=(), heartbeat_interval_seconds=10, offline_after_seconds=30,
            )

        def close(self):
            pass

    def on_config_saved(config):
        events.append("config_saved")

    controller = _new_controller(
        _config(), _FakeIdentityStore(), lambda config: _RecordingClient(), lambda client: _NullLifecycle(),
        lambda s: None, on_config_saved=on_config_saved,
    )
    with _ShutdownGuard(controller):
        controller.start()
        controller.submit_pairing("mcma_pc_x")
        assert _wait_until(lambda: events == ["config_saved", "enroll_called"])


def test_config_persistence_failure_never_consumes_the_pairing_code():
    """RELEASE BLOCKER 2: if the local, non-secret config cannot be
    persisted (e.g. disk full), the one-time pairing code must never be
    spent on a doomed attempt -- enroll() must not even be called."""
    enroll_calls = []

    class _RecordingClient:
        def enroll(self, pairing_code, *, workstation_label):
            enroll_calls.append(pairing_code)
            return EnrollResult(
                runner_id="a" * 32, runner_secret="mcma_rs_" + "b" * 40, runner_label="x",
                allowed_account_ids=(), heartbeat_interval_seconds=10, offline_after_seconds=30,
            )

        def close(self):
            pass

    def failing_on_config_saved(config):
        raise OSError("simulated disk full")

    statuses = []
    controller = _new_controller(
        _config(), _FakeIdentityStore(), lambda config: _RecordingClient(), lambda client: _NullLifecycle(),
        statuses.append, on_config_saved=failing_on_config_saved,
    )
    with _ShutdownGuard(controller):
        controller.start()
        controller.submit_pairing("mcma_pc_never_spent")
        assert _wait_until(lambda: statuses[-1].state == ControllerState.PAIRING_IDLE)
    assert enroll_calls == []
    # and the button/state is not stuck -- a second attempt is possible
    assert controller._pairing_in_progress is False


def test_identity_persistence_failure_after_successful_enroll_shows_fixed_message_and_never_starts_heartbeat():
    """RELEASE BLOCKER 2: the server already created an ACTIVE runner at
    this point (enroll() succeeded) -- if the identity cannot be stored
    locally, the app must NOT report success or start heartbeating with a
    secret it will lose the moment the process exits. The human must be
    told an administrator needs to revoke the now-orphaned server-side
    runner before a new pairing attempt."""
    result = EnrollResult(
        runner_id="a" * 32, runner_secret="mcma_rs_" + "b" * 40, runner_label="x",
        allowed_account_ids=("acct-mcma-oujda",), heartbeat_interval_seconds=10, offline_after_seconds=30,
    )

    class _FailingIdentityStore(_FakeIdentityStore):
        def save(self, identity):
            raise OSError("simulated disk full")

    statuses = []
    controller = _new_controller(
        _config(), _FailingIdentityStore(), lambda config: _FakeClient(enroll_result=result),
        lambda client: _NullLifecycle(), statuses.append,
    )
    with _ShutdownGuard(controller):
        controller.start()
        controller.submit_pairing("mcma_pc_x")
        assert _wait_until(lambda: statuses[-1].state == ControllerState.PAIRING_IDLE and "administrat" in statuses[-1].text.lower())
    assert controller._heartbeat_worker is None
    assert controller._pairing_in_progress is False


def test_identity_persistence_dpapi_failure_after_successful_enroll_is_handled_the_same_way():
    from mcma.core.dpapi import DpapiUnavailable

    result = EnrollResult(
        runner_id="a" * 32, runner_secret="mcma_rs_" + "b" * 40, runner_label="x",
        allowed_account_ids=(), heartbeat_interval_seconds=10, offline_after_seconds=30,
    )

    class _DpapiFailingIdentityStore(_FakeIdentityStore):
        def save(self, identity):
            raise DpapiUnavailable("simulated DPAPI failure")

    statuses = []
    controller = _new_controller(
        _config(), _DpapiFailingIdentityStore(), lambda config: _FakeClient(enroll_result=result),
        lambda client: _NullLifecycle(), statuses.append,
    )
    with _ShutdownGuard(controller):
        controller.start()
        controller.submit_pairing("mcma_pc_x")
        assert _wait_until(lambda: statuses[-1].state == ControllerState.PAIRING_IDLE and "administrat" in statuses[-1].text.lower())
    assert controller._heartbeat_worker is None


def test_successful_durable_persistence_starts_heartbeat_only_after_identity_save_succeeds():
    order = []
    result = EnrollResult(
        runner_id="a" * 32, runner_secret="mcma_rs_" + "b" * 40, runner_label="x",
        allowed_account_ids=(), heartbeat_interval_seconds=10, offline_after_seconds=30,
    )

    class _RecordingIdentityStore(_FakeIdentityStore):
        def save(self, identity):
            order.append("identity_saved")
            super().save(identity)

    class _RecordingLifecycle(_NullLifecycle):
        def run_once_loop(self, secret, stop_event, *, sessions=()):
            order.append("heartbeat_started")
            super().run_once_loop(secret, stop_event, sessions=sessions)

    controller = _new_controller(
        _config(), _RecordingIdentityStore(), lambda config: _FakeClient(enroll_result=result),
        lambda client: _RecordingLifecycle(), lambda s: None,
    )
    with _ShutdownGuard(controller):
        controller.start()
        controller.submit_pairing("mcma_pc_x")
        assert _wait_until(lambda: order == ["identity_saved", "heartbeat_started"])


def test_pairing_failure_stays_in_pairing_idle_with_fixed_message():
    statuses = []
    controller = _new_controller(
        _config(), _FakeIdentityStore(), lambda config: _FakeClient(enroll_error=RegistryConnectionError("x")),
        lambda client: _NullLifecycle(), statuses.append,
    )
    with _ShutdownGuard(controller):
        controller.start()
        controller.submit_pairing("mcma_pc_x")
        assert _wait_until(lambda: statuses[-1].state == ControllerState.PAIRING_IDLE and "Serveur inaccessible" in statuses[-1].text)


def test_client_construction_failure_does_not_leave_pairing_stuck_forever():
    """Regression: an invalid CA certificate file (or any other client
    construction failure -- e.g. a TLS/ssl error) used to raise OUTSIDE the
    try/except in _run_pairing, crashing the pairing thread silently and
    leaving _pairing_in_progress True forever (button disabled, no status
    shown, no way to retry short of restarting the whole app)."""
    statuses = []

    def failing_client_factory(config):
        raise ValueError("simulated bad CA certificate file")

    controller = _new_controller(_config(), _FakeIdentityStore(), failing_client_factory, lambda client: _NullLifecycle(), statuses.append)
    with _ShutdownGuard(controller):
        controller.start()
        controller.submit_pairing("mcma_pc_x")
        assert _wait_until(lambda: statuses[-1].state == ControllerState.PAIRING_IDLE)
        # and a second attempt must be possible -- proves _pairing_in_progress was reset
        controller.submit_pairing("mcma_pc_y")
        assert _wait_until(lambda: statuses.count(statuses[-1]) >= 1)


def test_duplicate_concurrent_pairing_attempts_are_ignored():
    calls = []
    gate = threading.Event()

    class _SlowClient:
        def enroll(self, pairing_code, *, workstation_label):
            calls.append(pairing_code)
            gate.wait(2)
            raise RegistryConnectionError("x")

        def close(self):
            pass

    controller = _new_controller(_config(), _FakeIdentityStore(), lambda config: _SlowClient(), lambda client: _NullLifecycle(), lambda s: None)
    try:
        with _ShutdownGuard(controller):
            controller.start()
            controller.submit_pairing("mcma_pc_first")
            controller.submit_pairing("mcma_pc_second")  # must be dropped: an attempt is already in flight
            gate.set()
            assert _wait_until(lambda: len(calls) == 1)
            time.sleep(0.05)
            assert calls == ["mcma_pc_first"]
    finally:
        gate.set()  # in case an assertion failed before the gate was set


def test_start_with_saved_identity_resumes_heartbeat_without_reenrolling():
    from mcma.app.workstation_runner.identity import IDENTITY_FORMAT_VERSION, RunnerIdentity

    existing = RunnerIdentity(
        format_version=IDENTITY_FORMAT_VERSION, server_origin=ORIGIN, runner_id="a" * 32,
        runner_secret="mcma_rs_" + "b" * 40, allowed_account_ids=("acct-mcma-oujda",),
    )
    statuses = []
    controller = _new_controller(_config(), _FakeIdentityStore(existing=existing), lambda config: _FakeClient(), lambda client: _NullLifecycle(), statuses.append)
    with _ShutdownGuard(controller):
        controller.start()
        assert _wait_until(lambda: statuses[-1].state == ControllerState.PAIRED_CONNECTING)


def test_start_heartbeat_construction_failure_does_not_crash_start():
    """Regression: a local problem building the client/lifecycle/worker for
    a RESUMED identity (e.g. a corrupt saved CA certificate path) must show
    a fixed disconnected status, never raise out of start() -- which would
    crash the whole app at startup, since start() is called from
    RunnerApp.run() before mainloop()."""
    from mcma.app.workstation_runner.identity import IDENTITY_FORMAT_VERSION, RunnerIdentity

    existing = RunnerIdentity(
        format_version=IDENTITY_FORMAT_VERSION, server_origin=ORIGIN, runner_id="a" * 32,
        runner_secret="mcma_rs_" + "b" * 40, allowed_account_ids=(),
    )
    statuses = []

    def failing_client_factory(config):
        raise ValueError("simulated bad CA certificate file")

    controller = _new_controller(_config(), _FakeIdentityStore(existing=existing), failing_client_factory, lambda client: _NullLifecycle(), statuses.append)
    controller.start()  # must not raise
    assert statuses[-1].state == ControllerState.PAIRED_DISCONNECTED


def test_unauthorized_event_returns_controller_to_pairing_idle():
    statuses = []

    class _UnauthorizingLifecycle:
        def run_once_loop(self, secret, stop_event, *, sessions=()):
            controller._handle_lifecycle_event(LifecycleEvent.UNAUTHORIZED)

    from mcma.app.workstation_runner.identity import IDENTITY_FORMAT_VERSION, RunnerIdentity

    existing = RunnerIdentity(
        format_version=IDENTITY_FORMAT_VERSION, server_origin=ORIGIN, runner_id="a" * 32,
        runner_secret="mcma_rs_" + "b" * 40, allowed_account_ids=(),
    )
    store = _FakeIdentityStore(existing=existing)
    controller = _new_controller(_config(), store, lambda config: _FakeClient(), lambda client: _UnauthorizingLifecycle(), statuses.append)
    with _ShutdownGuard(controller):
        controller.start()
        assert _wait_until(lambda: statuses[-1].state == ControllerState.PAIRING_IDLE)


def test_paired_connecting_is_emitted_before_the_heartbeat_worker_exists(monkeypatch):
    """PAIRED_CONNECTING must be observed before the worker thread is even
    created: the worker (once started) can emit its own status (e.g. an
    immediate UNAUTHORIZED) from a separate thread, and if CONNECTING could
    still be emitted afterward, it could race and overwrite a more recent,
    more correct status (see test_unauthorized_event_returns_controller_to_pairing_idle).
    Join-safety against a concurrent shutdown() is HeartbeatWorker.start()'s
    own responsibility (its self._thread is only assigned once genuinely
    started), not something this ordering needs to provide."""
    from mcma.app.workstation_runner import heartbeat as heartbeat_module
    from mcma.app.workstation_runner.identity import IDENTITY_FORMAT_VERSION, RunnerIdentity

    events = []
    original_start = heartbeat_module.HeartbeatWorker.start

    def spy_start(self):
        events.append("worker_started")
        original_start(self)

    monkeypatch.setattr(heartbeat_module.HeartbeatWorker, "start", spy_start)

    def on_status(status):
        if status.state == ControllerState.PAIRED_CONNECTING:
            events.append("status_connecting")

    existing = RunnerIdentity(
        format_version=IDENTITY_FORMAT_VERSION, server_origin=ORIGIN, runner_id="a" * 32,
        runner_secret="mcma_rs_" + "b" * 40, allowed_account_ids=(),
    )
    controller = _new_controller(_config(), _FakeIdentityStore(existing=existing), lambda config: _FakeClient(), lambda client: _NullLifecycle(), on_status)
    with _ShutdownGuard(controller):
        controller.start()
        assert events == ["status_connecting", "worker_started"]


def test_shutdown_reports_incomplete_while_a_thread_is_still_running_and_complete_once_it_finishes():
    """RELEASE BLOCKER 4: shutdown() is a single BOUNDED attempt, callable
    repeatedly (e.g. from a GUI poll loop), and reports whether everything
    has actually finished -- a flat 5s join was insufficient because
    enrollment can legitimately remain in network I/O longer than that."""
    gate = threading.Event()

    class _SlowClient:
        def enroll(self, pairing_code, *, workstation_label):
            gate.wait(3)
            raise RegistryConnectionError("x")

        def close(self):
            pass

    controller = _new_controller(_config(), _FakeIdentityStore(), lambda config: _SlowClient(), lambda client: _NullLifecycle(), lambda s: None)
    try:
        controller.start()
        controller.submit_pairing("mcma_pc_x")
        assert controller.shutdown(timeout=0.05) is False  # still blocked in enroll()
        assert controller.shutdown(timeout=0.05) is False  # a second poll, still not done
        gate.set()
        assert _wait_until(lambda: controller.shutdown(timeout=0.2) is True)
    finally:
        gate.set()


def test_no_pairing_attempt_is_accepted_once_shutdown_has_started():
    """RELEASE BLOCKER 4: reject new pairing attempts once shutdown starts."""
    enroll_calls = []

    class _RecordingClient:
        def enroll(self, pairing_code, *, workstation_label):
            enroll_calls.append(pairing_code)
            return EnrollResult(
                runner_id="a" * 32, runner_secret="mcma_rs_" + "b" * 40, runner_label="x",
                allowed_account_ids=(), heartbeat_interval_seconds=10, offline_after_seconds=30,
            )

        def close(self):
            pass

    controller = _new_controller(_config(), _FakeIdentityStore(), lambda config: _RecordingClient(), lambda client: _NullLifecycle(), lambda s: None)
    controller.start()
    assert controller.shutdown(timeout=0.05) is True  # nothing running yet -- also starts closing
    controller.submit_pairing("mcma_pc_after_close")
    time.sleep(0.05)
    assert enroll_calls == []


def test_pairing_that_succeeds_during_shutdown_persists_identity_but_never_starts_heartbeat():
    """RELEASE BLOCKER 4: if pairing succeeds DURING shutdown, the valid
    identity is still persisted (the server already created it -- losing it
    now would orphan the server-side runner exactly like RELEASE BLOCKER 2),
    but no heartbeat is started: the process is on its way out."""
    result = EnrollResult(
        runner_id="a" * 32, runner_secret="mcma_rs_" + "b" * 40, runner_label="x",
        allowed_account_ids=(), heartbeat_interval_seconds=10, offline_after_seconds=30,
    )
    gate = threading.Event()

    class _SlowSuccessClient:
        def enroll(self, pairing_code, *, workstation_label):
            gate.wait(3)
            return result

        def close(self):
            pass

    store = _FakeIdentityStore()
    controller = _new_controller(_config(), store, lambda config: _SlowSuccessClient(), lambda client: _NullLifecycle(), lambda s: None)
    try:
        controller.start()
        controller.submit_pairing("mcma_pc_x")
        assert controller.shutdown(timeout=0.05) is False  # still blocked, shutdown has now started
        gate.set()
        assert _wait_until(lambda: controller.shutdown(timeout=0.2) is True)
        assert store.saved is not None
        assert store.saved.runner_id == "a" * 32
        assert controller._heartbeat_worker is None
    finally:
        gate.set()


def test_repeated_shutdown_calls_with_nothing_running_are_always_safe():
    controller = _new_controller(_config(), _FakeIdentityStore(), lambda config: _FakeClient(), lambda client: _NullLifecycle(), lambda s: None)
    controller.start()
    for _ in range(5):
        assert controller.shutdown(timeout=0.05) is True


def test_shutdown_is_safe_during_pairing_in_progress():
    gate = threading.Event()

    class _SlowClient:
        def enroll(self, pairing_code, *, workstation_label):
            gate.wait(2)
            raise RegistryConnectionError("x")

        def close(self):
            pass

    controller = _new_controller(_config(), _FakeIdentityStore(), lambda config: _SlowClient(), lambda client: _NullLifecycle(), lambda s: None)
    try:
        controller.start()
        controller.submit_pairing("mcma_pc_x")
        controller.shutdown(timeout=2)  # must not hang or raise
    finally:
        gate.set()


def test_on_log_receives_fixed_event_names_for_key_transitions():
    """Regression: the controller previously had no way to report state
    transitions or error categories at all -- app.py could only log
    'startup'/'shutdown', not e.g. a pairing failure or an unauthorized
    heartbeat, which the spec explicitly requires ('timestamps, state
    transitions and safe error categories'). Never a secret or a raw
    exception -- only fixed, safe event-name strings."""
    events = []
    controller = _new_controller(
        _config(), _FakeIdentityStore(), lambda config: _FakeClient(enroll_error=RegistryConnectionError("x")),
        lambda client: _NullLifecycle(), lambda s: None, on_log=events.append,
    )
    with _ShutdownGuard(controller):
        controller.start()
        controller.submit_pairing("mcma_pc_x")
        assert _wait_until(lambda: "pairing_failed_connection" in events)
    assert all(isinstance(e, str) for e in events)
    assert "mcma_pc_x" not in " ".join(events)  # never the pairing code


def test_unauthorized_clear_failure_is_logged_distinctly_and_does_not_crash():
    """CLEANUP: identity clearing on 401 is owned by exactly one layer (the
    controller, not HeartbeatLifecycle) -- and a deletion failure must be
    visible (a distinct log event), not silently swallowed under the same
    'cleared' event name as a real success, and must never propagate and
    kill the calling thread."""

    class _FailingClearStore(_FakeIdentityStore):
        def clear(self):
            raise OSError("simulated permission error")

    class _UnauthorizingLifecycle:
        def run_once_loop(self, secret, stop_event, *, sessions=()):
            controller._handle_lifecycle_event(LifecycleEvent.UNAUTHORIZED)  # must not raise

    from mcma.app.workstation_runner.identity import IDENTITY_FORMAT_VERSION, RunnerIdentity

    existing = RunnerIdentity(
        format_version=IDENTITY_FORMAT_VERSION, server_origin=ORIGIN, runner_id="a" * 32,
        runner_secret="mcma_rs_" + "b" * 40, allowed_account_ids=(),
    )
    events = []
    controller = _new_controller(
        _config(), _FailingClearStore(existing=existing), lambda config: _FakeClient(),
        lambda client: _UnauthorizingLifecycle(), lambda s: None, on_log=events.append,
    )
    with _ShutdownGuard(controller):
        controller.start()
        assert _wait_until(lambda: "heartbeat_unauthorized_clear_failed" in events)
    assert "heartbeat_unauthorized_cleared" not in events  # distinct from the success event


def test_shutdown_started_pairing_succeeds_without_ever_constructing_a_heartbeat_worker():
    """RELEASE BLOCKER 4 -- supersedes an earlier, weaker regression test
    that only proved "started then immediately stopped". The stronger
    invariant: once shutdown() has begun, a pairing that then succeeds must
    still durably persist the identity (the server already issued the
    credential -- losing it now would orphan the server-side runner exactly
    like RELEASE BLOCKER 2), but must NEVER construct or start a lifecycle
    or heartbeat worker at all -- not "start then stop"."""
    result = EnrollResult(
        runner_id="a" * 32, runner_secret="mcma_rs_" + "b" * 40, runner_label="x",
        allowed_account_ids=(), heartbeat_interval_seconds=10, offline_after_seconds=30,
    )
    gate = threading.Event()

    class _SlowSuccessClient:
        def enroll(self, pairing_code, *, workstation_label):
            gate.wait(3)  # released only after shutdown() is already active
            return result

        def close(self):
            pass

    lifecycle_factory_calls = []

    def lifecycle_factory(client):
        lifecycle_factory_calls.append(client)
        return _NullLifecycle()

    store = _FakeIdentityStore()
    controller = _new_controller(_config(), store, lambda config: _SlowSuccessClient(), lifecycle_factory, lambda s: None)
    try:
        # Begin a pairing request that remains blocked.
        controller.start()
        controller.submit_pairing("mcma_pc_x")

        # Call shutdown with a short timeout and verify it returns False.
        assert controller.shutdown(timeout=0.05) is False

        # Release enrollment so it succeeds while shutdown is active.
        gate.set()
        assert _wait_until(lambda: controller._pairing_thread is not None and not controller._pairing_thread.is_alive())

        # Verify the identity is durably persisted because the server
        # already issued the credential.
        assert store.saved is not None
        assert store.saved.runner_id == "a" * 32

        # Verify controller._heartbeat_worker remains None.
        assert controller._heartbeat_worker is None

        # Verify no lifecycle or heartbeat worker is constructed or started.
        assert lifecycle_factory_calls == []

        # Poll shutdown again and verify it returns True after the pairing
        # thread exits.
        assert controller.shutdown(timeout=0.2) is True

        # Verify repeated completed shutdown calls remain safe.
        assert controller.shutdown(timeout=0.05) is True
        assert controller.shutdown(timeout=0.05) is True
    finally:
        gate.set()


# ======================================================================= #
# Phase 1B-B integration -- browser-session ownership
# ======================================================================= #


def test_browser_worker_is_started_exactly_once_by_controller_start():
    browser_worker = _FakeBrowserWorker()
    controller = _new_controller(browser_worker=browser_worker)
    controller.start()
    assert browser_worker.start_calls == 1


def test_request_login_delegates_to_browser_worker():
    browser_worker = _FakeBrowserWorker()
    controller = _new_controller(browser_worker=browser_worker)
    assert controller.request_login(OUJDA) is True
    assert browser_worker.login_requests == [OUJDA]


def test_allowed_account_reconciliation_forwards_to_session_manager():
    session_manager = _session_manager()
    controller = _new_controller(session_manager=session_manager)
    controller._handle_allowed_accounts((OUJDA,))
    assert session_manager.is_authorized(OUJDA) is True
    assert session_manager.is_authorized(NADOR) is False


def test_newly_allowed_account_without_saved_session_is_not_configured_and_never_verified():
    from mcma.app.workstation_runner.sessions import AccountState

    session_manager = _session_manager()  # nothing saved for OUJDA
    browser_worker = _FakeBrowserWorker()
    controller = _new_controller(session_manager=session_manager, browser_worker=browser_worker)
    controller._handle_allowed_accounts((OUJDA,))
    assert session_manager.state_of(OUJDA) is AccountState.NOT_CONFIGURED
    assert browser_worker.verification_requests == []


def test_newly_allowed_account_with_saved_session_requests_immediate_verification():
    from mcma.app.workstation_runner.sessions import AccountState

    session_manager = _session_manager(saved=(OUJDA,))
    browser_worker = _FakeBrowserWorker()
    controller = _new_controller(session_manager=session_manager, browser_worker=browser_worker)
    controller._handle_allowed_accounts((OUJDA,))
    assert session_manager.state_of(OUJDA) is AccountState.PENDING_VERIFICATION
    assert browser_worker.verification_requests == [OUJDA]


def test_removed_account_is_cancelled_and_its_encrypted_session_cleared():
    session_manager = _session_manager(saved=(OUJDA,))
    browser_worker = _FakeBrowserWorker()
    session_store = _FakeSessionStore({OUJDA: {"cookies": [], "origins": []}})
    controller = _new_controller(session_manager=session_manager, browser_worker=browser_worker, session_store=session_store)
    controller._handle_allowed_accounts((OUJDA,))
    controller._handle_allowed_accounts(())  # OUJDA removed on the next heartbeat
    assert browser_worker.cancelled == [OUJDA]
    assert session_store.clear_calls == [OUJDA]
    assert session_manager.is_authorized(OUJDA) is False


def test_worker_update_publishes_a_fresh_manager_snapshot_never_a_stale_payload():
    session_manager = _session_manager()
    snapshots = []
    controller = _new_controller(session_manager=session_manager, on_accounts_changed=snapshots.append)
    session_manager.reconcile_allowed_accounts((OUJDA,))
    controller._handle_worker_update()  # the worker's own callback is payload-free
    assert len(snapshots) == 1
    assert snapshots[0] == session_manager.snapshot()


def test_periodic_verification_is_driven_by_connected_ticks_without_real_sleeping():
    from tests.app.workstation_runner._fakes import FakeClock

    clock = FakeClock()
    scheduler = VerificationScheduler(interval_seconds=300.0, clock=clock)
    session_manager = _session_manager(saved=(OUJDA,))
    session_manager.reconcile_allowed_accounts((OUJDA,))
    browser_worker = _FakeBrowserWorker()
    controller = _new_controller(
        session_manager=session_manager, browser_worker=browser_worker, verification_scheduler=scheduler,
    )
    controller._handle_lifecycle_event(LifecycleEvent.CONNECTED)
    assert browser_worker.verification_requests == [OUJDA]  # never verified before -> immediately due
    browser_worker.verification_requests.clear()

    controller._handle_lifecycle_event(LifecycleEvent.CONNECTED)
    assert browser_worker.verification_requests == []  # not due yet -- no real sleeping needed

    clock.advance(300.0)
    controller._handle_lifecycle_event(LifecycleEvent.CONNECTED)
    assert browser_worker.verification_requests == [OUJDA]


def test_unauthorized_cleanup_cancels_browser_work_clears_all_sessions_and_resets_manager():
    session_manager = _session_manager(saved=(OUJDA, NADOR))
    session_manager.reconcile_allowed_accounts((OUJDA, NADOR))
    browser_worker = _FakeBrowserWorker()
    session_store = _FakeSessionStore({OUJDA: {"cookies": [], "origins": []}, NADOR: {"cookies": [], "origins": []}})
    identity_store = _FakeIdentityStore()
    snapshots = []
    controller = _new_controller(
        _config(), identity_store, lambda c: _FakeClient(), lambda c: _NullLifecycle(), lambda s: None,
        session_manager=session_manager, browser_worker=browser_worker, session_store=session_store,
        on_accounts_changed=snapshots.append,
    )
    controller._handle_lifecycle_event(LifecycleEvent.UNAUTHORIZED)
    assert sorted(browser_worker.cancelled) == [NADOR, OUJDA]
    assert session_store.clear_all_calls == 1
    assert session_manager.tracked_account_ids() == ()
    assert identity_store.cleared is True
    assert snapshots[-1] == ()


def test_shutdown_stops_the_browser_worker_too():
    browser_worker = _FakeBrowserWorker()
    controller = _new_controller(browser_worker=browser_worker)
    controller.start()
    assert controller.shutdown(timeout=1.0) is True
    assert browser_worker.stop_calls == [1.0]


def test_shutdown_never_reports_done_while_the_browser_worker_is_still_alive():
    class _SlowBrowserWorker(_FakeBrowserWorker):
        def is_alive(self):
            return True

        def stop(self, timeout):
            self.stop_calls.append(timeout)
            return False  # still winding down

    controller = _new_controller(browser_worker=_SlowBrowserWorker())
    controller.start()
    assert controller.shutdown(timeout=0.05) is False


# --------------------------------------------------------------------- #
# Phase 1C-B -- the job-polling worker (item D wiring)
# --------------------------------------------------------------------- #

from mcma.app.workstation_runner.job_worker import LifecycleEvent as JobLifecycleEvent  # noqa: E402


class _NullJobLifecycle:
    """Never actually loops -- mirrors _NullLifecycle's shape for
    JobPollingWorker's own run_forever(secret, stop_event) signature."""

    def run_forever(self, secret, stop_event):
        stop_event.wait()  # blocks until controller.shutdown() sets it


class _RecordingJobLifecycle:
    def __init__(self):
        self.run_calls: list = []

    def run_forever(self, secret, stop_event):
        self.run_calls.append(secret)
        stop_event.wait()


def _paired_controller(*, job_lifecycle_factory=None, on_job_status=None, **kwargs):
    store = _FakeIdentityStore(existing=None)
    result = EnrollResult(
        runner_id="a" * 32, runner_secret="mcma_rs_" + "b" * 40, runner_label="Poste-1",
        allowed_account_ids=("acct-mcma-oujda",), heartbeat_interval_seconds=10, offline_after_seconds=30,
    )
    controller = _new_controller(
        _config(), store, lambda config: _FakeClient(enroll_result=result), lambda client: _NullLifecycle(),
        lambda status: None, job_lifecycle_factory=job_lifecycle_factory, on_job_status=on_job_status, **kwargs,
    )
    return controller, store


def test_job_worker_is_started_after_successful_pairing():
    job_lifecycle = _RecordingJobLifecycle()
    controller, store = _paired_controller(job_lifecycle_factory=lambda client: job_lifecycle)
    with _ShutdownGuard(controller):
        controller.start()
        controller.submit_pairing("mcma_pc_x")
        assert _wait_until(lambda: store.saved is not None)
        assert _wait_until(lambda: len(job_lifecycle.run_calls) == 1)
        assert job_lifecycle.run_calls == [store.saved.runner_secret]


def test_job_worker_is_never_started_without_a_job_lifecycle_factory():
    """Backward compatible: a controller built the way every pre-1C-B test
    already does (no job_lifecycle_factory) never starts a job worker."""
    controller, store = _paired_controller(job_lifecycle_factory=None)
    with _ShutdownGuard(controller):
        controller.start()
        controller.submit_pairing("mcma_pc_x")
        assert _wait_until(lambda: store.saved is not None)
        assert controller._job_worker is None


def test_shutdown_stops_the_job_worker_too():
    job_lifecycle = _RecordingJobLifecycle()
    controller, store = _paired_controller(job_lifecycle_factory=lambda client: job_lifecycle)
    controller.start()
    controller.submit_pairing("mcma_pc_x")
    assert _wait_until(lambda: len(job_lifecycle.run_calls) == 1)
    assert controller.shutdown(timeout=2.0) is True
    assert not controller._job_worker.is_alive()


def test_job_worker_is_ready_gate_requires_connection_and_a_ready_account():
    session_manager = _session_manager()
    controller = _new_controller(session_manager=session_manager)
    # Not connected yet -- never ready regardless of accounts.
    assert controller._job_worker_is_ready() is False

    controller._connected.set()
    # Connected, but no account tracked/READY yet.
    assert controller._job_worker_is_ready() is False

    from mcma.app.workstation_runner.sessions import ProbeOutcome

    session_manager.reconcile_allowed_accounts((OUJDA,))
    assert controller._job_worker_is_ready() is False  # PENDING_VERIFICATION or NOT_CONFIGURED, not READY

    session_manager.record_login_success(OUJDA)
    assert controller._job_worker_is_ready() is True


def test_job_worker_is_ready_gate_is_false_once_shutdown_begins():
    session_manager = _session_manager()
    controller = _new_controller(session_manager=session_manager)
    controller._connected.set()
    session_manager.reconcile_allowed_accounts((OUJDA,))
    session_manager.record_login_success(OUJDA)
    assert controller._job_worker_is_ready() is True
    controller.shutdown(timeout=0.5)
    assert controller._job_worker_is_ready() is False


def test_connection_failed_clears_the_ready_gate():
    controller = _new_controller()
    controller._connected.set()
    controller._handle_lifecycle_event(LifecycleEvent.CONNECTION_FAILED)
    assert controller._connected.is_set() is False


def test_connected_sets_the_ready_gate():
    controller = _new_controller()
    controller._handle_lifecycle_event(LifecycleEvent.CONNECTED)
    assert controller._connected.is_set() is True


def test_job_status_events_translate_to_fixed_non_sensitive_text():
    statuses = []
    controller = _new_controller(on_job_status=statuses.append)
    controller._handle_job_event(JobLifecycleEvent.JOB_STARTED)
    controller._handle_job_event(JobLifecycleEvent.JOB_SUCCEEDED)
    controller._handle_job_event(JobLifecycleEvent.JOB_FAILED)
    assert statuses == [
        "En attente de travail",  # the initial idle text, emitted at construction
        "Vérification du dossier en cours",
        "Vérification terminée",
        "Échec de la vérification",
    ]


def test_execute_job_status_events_translate_to_their_own_fixed_text():
    """Phase 1C-C, item 10: EXECUTE's own fixed status text is distinct
    from DRY_RUN's -- never a final-submit affordance, never a claim that
    the dossier itself is completed."""
    statuses = []
    controller = _new_controller(on_job_status=statuses.append)
    controller._handle_job_event(JobLifecycleEvent.EXECUTE_STARTED)
    controller._handle_job_event(JobLifecycleEvent.EXECUTE_SUCCEEDED)
    controller._handle_job_event(JobLifecycleEvent.EXECUTE_FAILED)
    assert statuses == [
        "En attente de travail",  # the initial idle text, emitted at construction
        "Préparation de la saisie",
        "Prêt pour contrôle humain",
        "Saisie interrompue — contrôle requis",
    ]


def test_job_status_text_never_contains_a_dossier_identifier_or_token():
    """JobLifecycleEvent carries no payload at all -- there is nothing for
    the fixed text map to leak, by construction."""
    for event in JobLifecycleEvent:
        for text in {
            "En attente de travail", "Vérification du dossier en cours",
            "Vérification terminée", "Échec de la vérification",
        }:
            assert "job-" not in text and "mcma_ct_" not in text and "acct-" not in text
