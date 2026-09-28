"""mcma.app.workstation_runner.browser_worker -- Phase 1B-B Pass 3A tests.

No Playwright, no real DPAPI, no mcma.portal object anywhere in this file
-- the injected portal operations and the session store are all
deterministic, hand-written fakes. The REAL WorkstationSessionManager is
used throughout (it is pure and already independently tested in
test_sessions.py), so these tests prove the worker's own orchestration
against real state-machine semantics, not a second fake of it.

Synchronization is event/barrier-based throughout (ControllableOperation
below), never a bare `time.sleep(N); assert ...`. The one exception is
_wait_until(), a bounded poll used only where no single event exists to
wait on (e.g. "this account becomes acceptable again") -- always time-
bounded, never unbounded, never the sole basis for a positive assertion
about ordering.
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import threading
import time

import pytest

from mcma.app.workstation_runner.browser_worker import BrowserSessionWorker, BrowserWorkerStartupFailed
from mcma.app.workstation_runner.sessions import AccountState, ProbeOutcome, WorkstationSessionManager

OUJDA = "acct-mcma-oujda"
NADOR = "acct-mcma-nador"
MARKER = "SECRET-COOKIE-VALUE-MARKER-zzz"


def _wait(event: threading.Event, timeout: float = 2.0) -> None:
    assert event.wait(timeout=timeout), "timed out waiting for event"


def _wait_until(predicate, timeout: float = 2.0, interval: float = 0.01) -> bool:
    deadline = time.monotonic() + timeout
    while True:
        if predicate():
            return True
        if time.monotonic() >= deadline:
            return predicate()
        time.sleep(interval)


# --------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------- #


class FakeSessionStore:
    def __init__(self, initial: dict | None = None):
        self._data: dict[str, dict] = dict(initial or {})
        self.load_calls: list[str] = []
        self.save_calls: list[str] = []
        self.clear_calls: list[str] = []
        self._save_exception: Exception | None = None
        self._clear_exception: Exception | None = None
        self._save_assertion = None  # optional callable(account_id) run INSIDE save()

    def load(self, account_id: str) -> dict | None:
        self.load_calls.append(account_id)
        return self._data.get(account_id)

    def save(self, account_id: str, storage_state: dict) -> None:
        self.save_calls.append(account_id)
        if self._save_assertion is not None:
            self._save_assertion(account_id)
        if self._save_exception is not None:
            raise self._save_exception
        self._data[account_id] = storage_state

    def clear(self, account_id: str) -> None:
        self.clear_calls.append(account_id)
        if self._clear_exception is not None:
            raise self._clear_exception
        self._data.pop(account_id, None)

    def fail_save(self, exc: Exception) -> None:
        self._save_exception = exc

    def fail_clear(self, exc: Exception) -> None:
        self._clear_exception = exc

    def assert_during_save(self, fn) -> None:
        self._save_assertion = fn


class BlockingSessionStore(FakeSessionStore):
    """A FakeSessionStore whose save()/clear() can be made to block (a
    plain, synchronous threading.Event.wait()) inside their critical
    section, so a test can deterministically observe "the mutation has
    already entered its non-interruptible section" and race cancel_account
    against it."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.save_entered = threading.Event()
        self.save_release = threading.Event()
        self.clear_entered = threading.Event()
        self.clear_release = threading.Event()
        self._block_save = False
        self._block_clear = False

    def block_save(self) -> "BlockingSessionStore":
        self._block_save = True
        return self

    def block_clear(self) -> "BlockingSessionStore":
        self._block_clear = True
        return self

    def save(self, account_id: str, storage_state: dict) -> None:
        if self._block_save:
            self.save_entered.set()
            self.save_release.wait(timeout=5.0)
        super().save(account_id, storage_state)

    def clear(self, account_id: str) -> None:
        if self._block_clear:
            self.clear_entered.set()
            self.clear_release.wait(timeout=5.0)
        super().clear(account_id)


class FailOnceLoadStore(FakeSessionStore):
    """load() raises once for a chosen account (the exact exception given),
    then behaves normally on every subsequent call."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._fail_once_accounts: dict[str, Exception] = {}

    def fail_load_once(self, account_id: str, exc: Exception) -> None:
        self._fail_once_accounts[account_id] = exc

    def load(self, account_id: str) -> dict | None:
        self.load_calls.append(account_id)
        pending = self._fail_once_accounts.pop(account_id, None)
        if pending is not None:
            raise pending
        return self._data.get(account_id)


class FakeSessionMaterial:
    def __init__(self, storage_state: dict, *, consume_exception: Exception | None = None):
        self._storage_state = storage_state
        self._consume_exception = consume_exception
        self._consumed = False
        self.consume_calls = 0

    def consume_for_handoff(self) -> dict:
        self.consume_calls += 1
        if self._consumed:
            raise RuntimeError("already consumed")
        self._consumed = True
        if self._consume_exception is not None:
            raise self._consume_exception
        return self._storage_state


class ControllableOperation:
    """One injectable async portal-operation stand-in. Never blocks the
    worker loop with a plain threading.Event.wait() -- the coroutine only
    ever awaits an asyncio.Event that lives on the WORKER's own loop; the
    TEST thread flips it via call_soon_threadsafe (.release()/.release_cleanup())."""

    def __init__(self):
        self.started = threading.Event()
        self.finished = threading.Event()
        self.calls: list[tuple] = []
        self.result: object = None
        self.exception: Exception | None = None
        self._hold = False
        self._slow_cleanup = False
        self._release_event: asyncio.Event | None = None
        self._cleanup_event: asyncio.Event | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def hold(self) -> "ControllableOperation":
        self._hold = True
        return self

    def enable_slow_cleanup(self) -> "ControllableOperation":
        self._slow_cleanup = True
        return self

    def release(self) -> None:
        assert self._loop is not None and self._release_event is not None
        self._loop.call_soon_threadsafe(self._release_event.set)

    def release_cleanup(self) -> None:
        assert self._loop is not None and self._cleanup_event is not None
        self._loop.call_soon_threadsafe(self._cleanup_event.set)

    async def __call__(self, *args):
        self.calls.append(args)
        self._loop = asyncio.get_running_loop()
        self._release_event = asyncio.Event()
        self._cleanup_event = asyncio.Event()
        self.started.set()
        if self._hold:
            try:
                await self._release_event.wait()
            except asyncio.CancelledError:
                if self._slow_cleanup:
                    await self._cleanup_event.wait()
                self.finished.set()
                raise
        if self.exception is not None:
            self.finished.set()
            raise self.exception
        self.finished.set()
        return self.result


class OperationRouter:
    """A single injectable callable that dispatches per account_id to its
    own ControllableOperation, so different accounts' commands genuinely
    exercise independent fakes while the worker is only ever given ONE
    perform_manual_login / verify_saved_session callable."""

    def __init__(self):
        self.ops: dict[str, ControllableOperation] = {}

    def for_account(self, account_id: str) -> ControllableOperation:
        return self.ops.setdefault(account_id, ControllableOperation())

    async def __call__(self, account_id, *rest):
        return await self.for_account(account_id)(*rest)


def _manager(saved=()) -> WorkstationSessionManager:
    saved = set(saved)
    return WorkstationSessionManager(has_saved_session=lambda a: a in saved)


def _authorized_manager(accounts=(OUJDA, NADOR), saved=()) -> WorkstationSessionManager:
    manager = _manager(saved=saved)
    manager.reconcile_allowed_accounts(accounts)
    return manager


def _worker(*, manager=None, store=None, login=None, verify=None, on_update=None) -> BrowserSessionWorker:
    return BrowserSessionWorker(
        session_manager=manager or _authorized_manager(),
        session_store=store or FakeSessionStore(),
        perform_manual_login=login or OperationRouter(),
        verify_saved_session=verify or OperationRouter(),
        on_update=on_update,
    )


# --------------------------------------------------------------------- #
# 1 -- one non-daemon thread, one event loop
# --------------------------------------------------------------------- #


def test_worker_uses_one_non_daemon_thread_and_one_event_loop():
    login = OperationRouter()
    verify = OperationRouter()
    store = FakeSessionStore({NADOR: {"cookies": [], "origins": []}})
    w = _worker(login=login, verify=verify, store=store)
    w.start()
    try:
        assert w.is_alive() is True
        assert w._thread.daemon is False
        manager = w._session_manager
        assert manager.is_authorized(OUJDA)
        assert w.request_login(OUJDA) is True
        _wait(login.for_account(OUJDA).started)
        loop_during_login = login.for_account(OUJDA)._loop
        login.for_account(OUJDA).release()
        _wait(login.for_account(OUJDA).finished)
        assert w.request_verification(NADOR) is True
        _wait(verify.for_account(NADOR).started)
        loop_during_verify = verify.for_account(NADOR)._loop
        verify.for_account(NADOR).release()
        _wait(verify.for_account(NADOR).finished)
        assert loop_during_login is loop_during_verify is w._loop
    finally:
        assert w.stop(timeout=2.0) is True


def test_start_is_idempotent():
    w = _worker()
    w.start()
    first_thread = w._thread
    w.start()
    assert w._thread is first_thread
    assert w.stop(timeout=2.0) is True


# --------------------------------------------------------------------- #
# 2 & 3 -- material consumed exactly once; save happens BEFORE READY
# --------------------------------------------------------------------- #


def test_successful_login_consumes_material_exactly_once_and_saves_before_ready():
    login = OperationRouter()
    store = FakeSessionStore()
    manager = _authorized_manager()
    material = FakeSessionMaterial({"cookies": [], "origins": []})
    login.for_account(OUJDA).result = material

    def _assert_not_yet_ready(account_id):
        assert manager.state_of(account_id) is not AccountState.READY

    store.assert_during_save(_assert_not_yet_ready)

    w = _worker(manager=manager, store=store, login=login)
    w.start()
    try:
        assert w.request_login(OUJDA) is True
        _wait(login.for_account(OUJDA).finished)
        assert _wait_until(lambda: manager.state_of(OUJDA) is AccountState.READY)
        assert material.consume_calls == 1
        assert store.save_calls == [OUJDA]
    finally:
        assert w.stop(timeout=2.0) is True


# --------------------------------------------------------------------- #
# 4 -- save/consume failure never reaches READY; produces ERROR
# --------------------------------------------------------------------- #


def test_save_failure_never_reaches_ready_and_produces_error():
    login = OperationRouter()
    store = FakeSessionStore()
    store.fail_save(RuntimeError(f"disk full {MARKER}"))
    manager = _authorized_manager()
    login.for_account(OUJDA).result = FakeSessionMaterial({"cookies": [], "origins": []})

    w = _worker(manager=manager, store=store, login=login)
    w.start()
    try:
        assert w.request_login(OUJDA) is True
        _wait(login.for_account(OUJDA).finished)
        assert _wait_until(lambda: manager.state_of(OUJDA) is AccountState.ERROR)
        assert manager.state_of(OUJDA) is not AccountState.READY
    finally:
        assert w.stop(timeout=2.0) is True


def test_consume_failure_never_reaches_ready_and_produces_error():
    login = OperationRouter()
    store = FakeSessionStore()
    manager = _authorized_manager()
    login.for_account(OUJDA).result = FakeSessionMaterial(
        {"cookies": [], "origins": []}, consume_exception=RuntimeError("boom"),
    )

    w = _worker(manager=manager, store=store, login=login)
    w.start()
    try:
        assert w.request_login(OUJDA) is True
        _wait(login.for_account(OUJDA).finished)
        assert _wait_until(lambda: manager.state_of(OUJDA) is AccountState.ERROR)
        assert store.save_calls == []
    finally:
        assert w.stop(timeout=2.0) is True


# --------------------------------------------------------------------- #
# 5 -- failed / timed-out / cancelled login does not replace old session
# --------------------------------------------------------------------- #


def test_failed_login_does_not_replace_the_old_session_and_state_is_untouched():
    login = OperationRouter()
    old_session = {"cookies": [{"name": "old", "value": "session", "domain": "d", "path": "/"}], "origins": []}
    store = FakeSessionStore({OUJDA: old_session})
    manager = _authorized_manager(saved=(OUJDA,))
    manager.reconcile_allowed_accounts((OUJDA, NADOR))  # OUJDA starts PENDING_VERIFICATION
    login.for_account(OUJDA).exception = RuntimeError("login timed out or window closed")

    w = _worker(manager=manager, store=store, login=login)
    w.start()
    try:
        assert w.request_login(OUJDA) is True
        _wait(login.for_account(OUJDA).finished)
        assert _wait_until(lambda: w.request_login(OUJDA) is True)  # account freed again -> op ran and completed
        assert store.load(OUJDA) == old_session
        assert store.save_calls == []
        # retain whatever it already was -- never forced to ERROR/READY by a login ATTEMPT failure
        assert manager.state_of(OUJDA) is AccountState.PENDING_VERIFICATION
    finally:
        assert w.stop(timeout=2.0) is True


def test_cancelled_login_does_not_replace_the_old_session():
    login = OperationRouter()
    old_session = {"cookies": [], "origins": []}
    store = FakeSessionStore({OUJDA: old_session})
    manager = _authorized_manager(saved=(OUJDA,))
    op = login.for_account(OUJDA).hold()

    w = _worker(manager=manager, store=store, login=login)
    w.start()
    try:
        assert w.request_login(OUJDA) is True
        _wait(op.started)
        w.cancel_account(OUJDA)
        _wait(op.finished)
        assert store.load(OUJDA) == old_session
        assert store.save_calls == []
    finally:
        assert w.stop(timeout=2.0) is True


# --------------------------------------------------------------------- #
# 6 & 7 -- global login exclusivity; duplicate verification rejected
# --------------------------------------------------------------------- #


def test_only_one_login_is_accepted_globally():
    login = OperationRouter()
    manager = _authorized_manager()
    op_a = login.for_account(OUJDA).hold()
    w = _worker(manager=manager, login=login)
    w.start()
    try:
        assert w.request_login(OUJDA) is True
        _wait(op_a.started)
        assert w.request_login(OUJDA) is False  # duplicate, same account
        assert w.request_login(NADOR) is False  # a DIFFERENT account -- still globally exclusive
        op_a.release()
        _wait(op_a.finished)
    finally:
        assert w.stop(timeout=2.0) is True


def test_duplicate_verification_for_the_same_account_is_rejected():
    verify = OperationRouter()
    manager = _authorized_manager(saved=(OUJDA,))
    store = FakeSessionStore({OUJDA: {"cookies": [], "origins": []}})
    op = verify.for_account(OUJDA).hold()
    w = _worker(manager=manager, store=store, verify=verify)
    w.start()
    try:
        assert w.request_verification(OUJDA) is True
        _wait(op.started)
        assert w.request_verification(OUJDA) is False
        op.release()
        _wait(op.finished)
    finally:
        assert w.stop(timeout=2.0) is True


# --------------------------------------------------------------------- #
# 8 -- operations are serialized (never two running concurrently)
# --------------------------------------------------------------------- #


def test_operations_for_different_accounts_are_serialized_not_concurrent():
    verify = OperationRouter()
    manager = _authorized_manager(saved=(OUJDA, NADOR))
    store = FakeSessionStore({OUJDA: {"cookies": [], "origins": []}, NADOR: {"cookies": [], "origins": []}})
    op_a = verify.for_account(OUJDA).hold()
    op_b = verify.for_account(NADOR)
    w = _worker(manager=manager, store=store, verify=verify)
    w.start()
    try:
        assert w.request_verification(OUJDA) is True
        _wait(op_a.started)
        assert w.request_verification(NADOR) is True  # accepted (queued), not yet running
        time.sleep(0.05)  # brief settle window -- the assertion below is the real proof
        assert op_b.started.is_set() is False  # B must NOT run while A is still held
        op_a.release()
        _wait(op_a.finished)
        _wait(op_b.started)
        op_b.release()
        _wait(op_b.finished)
    finally:
        assert w.stop(timeout=2.0) is True


# --------------------------------------------------------------------- #
# 9 -- unauthorized account requests are rejected
# --------------------------------------------------------------------- #


def test_unauthorized_account_requests_are_rejected():
    manager = _authorized_manager(accounts=(OUJDA,))  # NADOR never authorized
    w = _worker(manager=manager)
    w.start()
    try:
        assert w.request_login(NADOR) is False
        assert w.request_verification(NADOR) is False
        assert w.request_login("acct-mamda-oujda") is False
        assert w.request_verification("not-a-real-account") is False
    finally:
        assert w.stop(timeout=2.0) is True


# --------------------------------------------------------------------- #
# 10 -- a cancelled QUEUED command never executes
# --------------------------------------------------------------------- #


def test_cancelled_queued_command_never_executes():
    verify = OperationRouter()
    manager = _authorized_manager(saved=(OUJDA, NADOR))
    store = FakeSessionStore({OUJDA: {"cookies": [], "origins": []}, NADOR: {"cookies": [], "origins": []}})
    op_a = verify.for_account(OUJDA).hold()
    op_b = verify.for_account(NADOR)
    w = _worker(manager=manager, store=store, verify=verify)
    w.start()
    try:
        assert w.request_verification(OUJDA) is True
        _wait(op_a.started)
        assert w.request_verification(NADOR) is True  # queued, not yet started
        w.cancel_account(NADOR)
        op_a.release()
        _wait(op_a.finished)
        # NADOR must become acceptable again (its stale queued command was
        # discarded, never launched) -- a definitive, event-driven proof.
        assert _wait_until(lambda: w.request_verification(NADOR) is True)
        assert op_b.calls == [] or len(op_b.calls) == 1  # only the SECOND (post-cancel) request may have run
    finally:
        assert w.stop(timeout=2.0) is True


# --------------------------------------------------------------------- #
# 11 -- account removal during active op: stale result cannot restore it
# --------------------------------------------------------------------- #


def test_account_removal_during_active_operation_cannot_be_restored_by_stale_result():
    verify = OperationRouter()
    manager = _authorized_manager(saved=(OUJDA,))
    store = FakeSessionStore({OUJDA: {"cookies": [], "origins": []}})
    op = verify.for_account(OUJDA).hold()
    w = _worker(manager=manager, store=store, verify=verify)
    w.start()
    try:
        assert w.request_verification(OUJDA) is True
        _wait(op.started)
        manager.reconcile_allowed_accounts(())  # OUJDA removed, worker never told directly
        op.result = "AUTHENTICATED"
        op.release()
        _wait(op.finished)
        time.sleep(0.05)  # let the (discarded) result-application path run
        assert manager.is_authorized(OUJDA) is False
        assert manager.state_of(OUJDA) is None
    finally:
        assert w.stop(timeout=2.0) is True


# --------------------------------------------------------------------- #
# 12-16 -- verification outcome mapping
# --------------------------------------------------------------------- #


def test_authenticated_verification_sets_ready_and_retains_stored_session():
    verify = OperationRouter()
    session = {"cookies": [], "origins": []}
    store = FakeSessionStore({OUJDA: session})
    manager = _authorized_manager(saved=(OUJDA,))
    verify.for_account(OUJDA).result = "AUTHENTICATED"
    w = _worker(manager=manager, store=store, verify=verify)
    w.start()
    try:
        assert w.request_verification(OUJDA) is True
        _wait(verify.for_account(OUJDA).finished)
        assert _wait_until(lambda: manager.state_of(OUJDA) is AccountState.READY)
        assert store.load(OUJDA) == session
        assert store.clear_calls == []
    finally:
        assert w.stop(timeout=2.0) is True


def test_logged_out_clears_first_then_sets_login_required():
    verify = OperationRouter()
    session = {"cookies": [], "origins": []}
    store = FakeSessionStore({OUJDA: session})
    manager = _authorized_manager(saved=(OUJDA,))
    verify.for_account(OUJDA).result = "LOGGED_OUT"
    w = _worker(manager=manager, store=store, verify=verify)
    w.start()
    try:
        assert w.request_verification(OUJDA) is True
        _wait(verify.for_account(OUJDA).finished)
        assert _wait_until(lambda: manager.state_of(OUJDA) is AccountState.LOGIN_REQUIRED)
        assert store.clear_calls == [OUJDA]
        assert store.load(OUJDA) is None
    finally:
        assert w.stop(timeout=2.0) is True


def test_logged_out_clear_failure_produces_error_not_login_required():
    verify = OperationRouter()
    store = FakeSessionStore({OUJDA: {"cookies": [], "origins": []}})
    store.fail_clear(RuntimeError(f"disk error {MARKER}"))
    manager = _authorized_manager(saved=(OUJDA,))
    verify.for_account(OUJDA).result = "LOGGED_OUT"
    w = _worker(manager=manager, store=store, verify=verify)
    w.start()
    try:
        assert w.request_verification(OUJDA) is True
        _wait(verify.for_account(OUJDA).finished)
        assert _wait_until(lambda: manager.state_of(OUJDA) is AccountState.ERROR)
        assert manager.state_of(OUJDA) is not AccountState.LOGIN_REQUIRED
    finally:
        assert w.stop(timeout=2.0) is True


def test_indeterminate_verification_sets_error_and_retains_stored_session():
    verify = OperationRouter()
    session = {"cookies": [], "origins": []}
    store = FakeSessionStore({OUJDA: session})
    manager = _authorized_manager(saved=(OUJDA,))
    verify.for_account(OUJDA).result = "INDETERMINATE"
    w = _worker(manager=manager, store=store, verify=verify)
    w.start()
    try:
        assert w.request_verification(OUJDA) is True
        _wait(verify.for_account(OUJDA).finished)
        assert _wait_until(lambda: manager.state_of(OUJDA) is AccountState.ERROR)
        assert store.load(OUJDA) == session
    finally:
        assert w.stop(timeout=2.0) is True


def test_verification_exception_sets_error_and_retains_stored_session():
    verify = OperationRouter()
    session = {"cookies": [], "origins": []}
    store = FakeSessionStore({OUJDA: session})
    manager = _authorized_manager(saved=(OUJDA,))
    verify.for_account(OUJDA).exception = RuntimeError(f"probe crashed {MARKER}")
    w = _worker(manager=manager, store=store, verify=verify)
    w.start()
    try:
        assert w.request_verification(OUJDA) is True
        _wait(verify.for_account(OUJDA).finished)
        assert _wait_until(lambda: manager.state_of(OUJDA) is AccountState.ERROR)
        assert store.load(OUJDA) == session
    finally:
        assert w.stop(timeout=2.0) is True


# --------------------------------------------------------------------- #
# 17 -- missing/corrupt saved state: portal op never called, never READY
# --------------------------------------------------------------------- #


def test_missing_saved_state_never_calls_portal_op_and_never_becomes_ready():
    verify = OperationRouter()
    store = FakeSessionStore()  # nothing saved for OUJDA
    manager = _authorized_manager(accounts=(OUJDA,))  # NOT_CONFIGURED at reconcile time
    # Force a DIFFERENT state first so the wait below proves a REAL
    # transition happened (state already being NOT_CONFIGURED before the
    # request would make that wait vacuously true without the command ever
    # having run).
    manager.record_probe_outcome(OUJDA, ProbeOutcome.AUTHENTICATED)
    w = _worker(manager=manager, store=store, verify=verify)
    w.start()
    try:
        assert manager.state_of(OUJDA) is AccountState.READY
        assert w.request_verification(OUJDA) is True
        assert _wait_until(lambda: manager.state_of(OUJDA) is AccountState.NOT_CONFIGURED)
        assert verify.for_account(OUJDA).calls == []
        assert OUJDA in store.load_calls
        assert manager.state_of(OUJDA) is not AccountState.READY
    finally:
        assert w.stop(timeout=2.0) is True


# --------------------------------------------------------------------- #
# 18 -- cancellation uses the worker's own event loop safely
# --------------------------------------------------------------------- #


def test_cancel_account_cancels_the_active_task_via_the_worker_loop():
    login = OperationRouter()
    manager = _authorized_manager()
    op = login.for_account(OUJDA).hold()
    w = _worker(manager=manager, login=login)
    w.start()
    try:
        assert w.request_login(OUJDA) is True
        _wait(op.started)
        assert threading.current_thread() is not w._thread  # cancel called from the TEST thread
        w.cancel_account(OUJDA)
        _wait(op.finished)
        # no state corruption from the cancellation -- never forced to ERROR/READY
        assert manager.state_of(OUJDA) not in (AccountState.READY, AccountState.ERROR)
    finally:
        assert w.stop(timeout=2.0) is True


# --------------------------------------------------------------------- #
# 19, 20, 21 -- stop() during an active login: immediate vs slow cleanup
# --------------------------------------------------------------------- #


def test_stop_during_login_cancels_it_waits_for_cleanup_and_exits():
    login = OperationRouter()
    op = login.for_account(OUJDA).hold()
    w = _worker(login=login)
    w.start()
    assert w.request_login(OUJDA) is True
    _wait(op.started)
    assert w.stop(timeout=2.0) is True
    assert op.finished.is_set()
    assert w.is_alive() is False


def test_short_stop_timeout_returns_false_while_thread_genuinely_alive_then_later_stop_succeeds():
    login = OperationRouter()
    op = login.for_account(OUJDA).hold().enable_slow_cleanup()
    w = _worker(login=login)
    w.start()
    assert w.request_login(OUJDA) is True
    _wait(op.started)
    assert w.stop(timeout=0.05) is False
    assert w.is_alive() is True
    op.release_cleanup()
    assert w.stop(timeout=2.0) is True
    assert w.is_alive() is False


def test_repeated_stop_calls_are_safe():
    w = _worker()
    w.start()
    assert w.stop(timeout=2.0) is True
    assert w.stop(timeout=2.0) is True
    assert w.stop(timeout=0.01) is True


def test_stop_before_start_is_a_safe_noop():
    w = _worker()
    assert w.stop(timeout=1.0) is True
    assert w.is_alive() is False


# --------------------------------------------------------------------- #
# 22 -- no secret marker ever appears in callbacks / repr
# --------------------------------------------------------------------- #


def test_no_secret_marker_appears_in_update_callbacks_or_repr():
    login = OperationRouter()
    store = FakeSessionStore()
    manager = _authorized_manager()
    login.for_account(OUJDA).result = FakeSessionMaterial(
        {"cookies": [{"name": "s", "value": MARKER, "domain": "d", "path": "/"}], "origins": []},
    )
    updates: list[tuple] = []
    w = _worker(manager=manager, store=store, login=login, on_update=lambda *args: updates.append(args))
    w.start()
    try:
        assert w.request_login(OUJDA) is True
        _wait(login.for_account(OUJDA).finished)
        assert _wait_until(lambda: manager.state_of(OUJDA) is AccountState.READY)
        for call in updates:
            for value in call:
                assert MARKER not in str(value)
                assert MARKER not in repr(value)
        assert MARKER not in repr(w)
        assert MARKER not in str(w)
    finally:
        assert w.stop(timeout=2.0) is True


def test_update_callback_is_payload_free():
    """OnUpdate is Callable[[], None] -- a pure change signal. It can
    structurally never carry account_id/AccountState, so the future
    controller must react by reading a fresh WorkstationSessionManager
    snapshot instead."""
    login = OperationRouter()
    manager = _authorized_manager()
    login.for_account(OUJDA).result = FakeSessionMaterial({"cookies": [], "origins": []})
    updates: list[tuple] = []
    w = _worker(manager=manager, login=login, on_update=lambda *args: updates.append(args))
    w.start()
    try:
        assert w.request_login(OUJDA) is True
        _wait(login.for_account(OUJDA).finished)
        assert _wait_until(lambda: len(updates) > 0)
        for call in updates:
            assert call == ()
    finally:
        assert w.stop(timeout=2.0) is True


def test_callback_failure_never_breaks_the_worker():
    login = OperationRouter()
    manager = _authorized_manager()
    login.for_account(OUJDA).result = FakeSessionMaterial({"cookies": [], "origins": []})

    def _bad_callback(*args):
        raise RuntimeError("callback exploded")

    w = _worker(manager=manager, login=login, on_update=_bad_callback)
    w.start()
    try:
        assert w.request_login(OUJDA) is True
        _wait(login.for_account(OUJDA).finished)
        assert _wait_until(lambda: manager.state_of(OUJDA) is AccountState.READY)
        assert w.is_alive() is True
    finally:
        assert w.stop(timeout=2.0) is True


# --------------------------------------------------------------------- #
# 23 -- import boundary: no portal, Playwright, Tk, HTTP, DB, writer,
# form-filling module anywhere in this module's own imports
# --------------------------------------------------------------------- #


def test_module_declares_no_forbidden_imports():
    import mcma.app.workstation_runner.browser_worker as browser_worker_module

    source = inspect.getsource(browser_worker_module)
    tree = ast.parse(source)
    imported_modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)
    forbidden_prefixes = (
        "playwright", "tkinter", "sqlite3", "fastapi", "httpx", "requests",
        "mcma.portal", "mcma.persistence", "mcma.app.workstation_runner.http_client",
        "mcma.app.workstation_runner.gui", "mcma.app.workstation_runner.controller",
        "mcma.app.workstation_runner.app",
    )
    for module_name in imported_modules:
        assert not any(
            module_name == prefix or module_name.startswith(prefix + ".") for prefix in forbidden_prefixes
        ), module_name


# ======================================================================= #
# Pass 3A concurrency correction -- findings 1-6
# ======================================================================= #


# --------------------------------------------------------------------- #
# Finding 1 -- linearizable start/stop lifecycle
# --------------------------------------------------------------------- #


def test_race_start_and_stop_never_leaves_an_orphan_thread():
    """Repeatedly races start() and stop() from two independent threads
    (a Barrier synchronizes their launch as tightly as the OS allows).
    Whatever the actual interleaving, no non-daemon worker thread may
    survive once both calls have returned."""
    for _ in range(20):
        w = _worker()
        barrier = threading.Barrier(2)

        def _start():
            barrier.wait()
            w.start()

        def _stop():
            barrier.wait()
            w.stop(timeout=2.0)

        t1 = threading.Thread(target=_start)
        t2 = threading.Thread(target=_stop)
        t1.start()
        t2.start()
        t1.join(timeout=5.0)
        t2.join(timeout=5.0)
        w.stop(timeout=2.0)  # make certain, regardless of which raced first
        assert not any(t.name == "mcma-runner-browser-worker" for t in threading.enumerate())


def test_stop_before_start_then_start_remains_stopped():
    w = _worker()
    assert w.stop(timeout=1.0) is True
    w.start()
    assert w.is_alive() is False
    assert w._thread is None


def test_concurrent_duplicate_starts_create_at_most_one_thread():
    w = _worker()
    barrier = threading.Barrier(5)

    def _start():
        barrier.wait()
        w.start()

    threads = [threading.Thread(target=_start) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5.0)
    try:
        matching = [t for t in threading.enumerate() if t.name == "mcma-runner-browser-worker"]
        assert len(matching) == 1
        assert w.is_alive() is True
    finally:
        assert w.stop(timeout=2.0) is True


def test_delayed_loop_initialization_followed_by_stop_leaves_no_orphan():
    w = _worker()
    construction_started = threading.Event()
    release_construction = threading.Event()

    def _delayed_new_event_loop():
        construction_started.set()
        release_construction.wait(timeout=5.0)
        return asyncio.new_event_loop()

    w._new_event_loop = _delayed_new_event_loop  # test-only instance-level seam

    start_thread = threading.Thread(target=w.start)
    start_thread.start()
    _wait(construction_started)

    # stop() runs here, genuinely while self._loop does not exist yet --
    # exercises the _stop_requested_before_loop path.
    assert w.stop(timeout=0.2) is False  # bounded: construction is still blocked
    assert w.is_alive() is True

    release_construction.set()
    assert w.stop(timeout=2.0) is True
    assert w.is_alive() is False
    start_thread.join(timeout=2.0)
    assert not start_thread.is_alive()
    assert not any(t.name == "mcma-runner-browser-worker" for t in threading.enumerate())


def test_loop_construction_failure_fails_closed_without_orphan_thread():
    """Regression for the exact failure independent review reproduced:
    is_alive() observed True immediately after start() returned, because
    start() trusted `_loop_ready` alone as proof the thread had finished --
    it can fire strictly before the OS thread's own teardown completes.
    start() must now perform its own bounded, reliable thread.join() (via
    stop()) before ever reporting failure, so is_alive() is False the
    INSTANT start() raises -- checked here with no sleep at all, exactly
    as the failing report did."""
    w = _worker()

    def _failing_new_event_loop():
        raise RuntimeError("simulated event loop construction failure")

    w._new_event_loop = _failing_new_event_loop
    with pytest.raises(BrowserWorkerStartupFailed):
        w.start()
    assert w.is_alive() is False  # must hold with ZERO settle time
    assert w.stop(timeout=1.0) is True


def test_loop_construction_failure_is_reliable_across_many_repetitions():
    """The original bug was a genuine race, not a deterministic failure --
    a single passing run does not prove it is fixed. Repeats the exact
    check many times with fresh workers."""
    for _ in range(50):
        w = _worker()

        def _failing_new_event_loop():
            raise RuntimeError("simulated event loop construction failure")

        w._new_event_loop = _failing_new_event_loop
        with pytest.raises(BrowserWorkerStartupFailed):
            w.start()
        assert w.is_alive() is False
    assert not any(t.name == "mcma-runner-browser-worker" for t in threading.enumerate())


# --------------------------------------------------------------------- #
# Pass 3B correction, finding 2 -- threading.Thread.start() itself failing
# --------------------------------------------------------------------- #


def test_thread_start_failure_fails_closed_and_stop_stays_safe(monkeypatch):
    w = _worker()

    class _FailingThread:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            raise RuntimeError("simulated OS thread creation failure")

    import mcma.app.workstation_runner.browser_worker as browser_worker_module

    monkeypatch.setattr(browser_worker_module.threading, "Thread", _FailingThread)
    with pytest.raises(BrowserWorkerStartupFailed):
        w.start()

    # A truthful terminal state -- never STARTING with a reference to an
    # unstarted thread that a later stop() might try to join().
    assert w._thread is None
    assert w.is_alive() is False
    assert w.stop(timeout=1.0) is True  # safe, idempotent -- no join() on anything
    assert w.stop(timeout=1.0) is True  # repeated call remains safe

    # The stopped-worker-is-terminal policy is unchanged: a later start()
    # must not create a second thread.
    w.start()
    assert w.is_alive() is False
    assert w._thread is None


# --------------------------------------------------------------------- #
# Finding 2 -- request acceptance atomic with shutdown
# --------------------------------------------------------------------- #


def test_enqueue_failure_rolls_back_bookkeeping_and_returns_false():
    login = OperationRouter()
    manager = _authorized_manager()
    w = _worker(manager=manager, login=login)
    w.start()
    try:
        real_call_soon_threadsafe = w._loop.call_soon_threadsafe

        def _failing_call_soon_threadsafe(*args, **kwargs):
            raise RuntimeError("Event loop is closed")

        w._loop.call_soon_threadsafe = _failing_call_soon_threadsafe
        assert w.request_login(OUJDA) is False
        assert OUJDA not in w._pending_or_active_accounts
        assert w._login_account_id is None

        w._loop.call_soon_threadsafe = real_call_soon_threadsafe
        assert w.request_login(OUJDA) is True
        _wait(login.for_account(OUJDA).finished)
    finally:
        assert w.stop(timeout=2.0) is True


def test_request_vs_stop_race_never_lets_an_exception_escape():
    login = OperationRouter()
    verify = OperationRouter()
    manager = _authorized_manager()
    w = _worker(manager=manager, login=login, verify=verify)
    w.start()

    hammer_stop = threading.Event()
    errors: list[Exception] = []

    def _hammer():
        while not hammer_stop.is_set():
            try:
                w.request_login(OUJDA)
                w.request_verification(NADOR)
            except Exception as exc:  # pragma: no cover -- must never happen
                errors.append(exc)

    hammer_thread = threading.Thread(target=_hammer)
    hammer_thread.start()
    time.sleep(0.05)
    assert w.stop(timeout=2.0) is True
    hammer_stop.set()
    hammer_thread.join(timeout=2.0)

    assert errors == []
    assert w.request_login(OUJDA) is False
    assert w.request_verification(NADOR) is False


# --------------------------------------------------------------------- #
# Pass 3B correction, finding 3 -- stop/request admission linearization,
# deterministic barrier (not only the stress test above)
# --------------------------------------------------------------------- #


def test_stop_admission_barrier_rejects_requests_then_completes_cleanly():
    """Pauses stop() EXACTLY after it has closed request admission (the
    single linearization point) and before any lifecycle/loop work runs.
    Requests issued during that pause must already be rejected; releasing
    the pause must then let stop() terminate cleanly."""
    login = OperationRouter()
    manager = _authorized_manager()
    w = _worker(manager=manager, login=login)
    w.start()

    paused = threading.Event()
    release = threading.Event()

    def _pause_hook():
        paused.set()
        release.wait(timeout=5.0)

    w._after_admission_closed = _pause_hook

    stop_result = {}

    def _stop():
        stop_result["value"] = w.stop(timeout=2.0)

    stop_thread = threading.Thread(target=_stop)
    stop_thread.start()
    _wait(paused)

    # Admission is now closed, but lifecycle/join work is deliberately
    # paused -- requests issued right now must already be rejected.
    assert w.request_login(OUJDA) is False
    assert w.request_verification(NADOR) is False

    release.set()
    stop_thread.join(timeout=5.0)
    assert stop_result["value"] is True
    assert w.is_alive() is False


# --------------------------------------------------------------------- #
# Finding 3 -- cancellation cannot be missed during task publication
# --------------------------------------------------------------------- #


def test_cancel_during_task_publication_window_prevents_coroutine_from_running():
    login = OperationRouter()
    manager = _authorized_manager()
    w = _worker(manager=manager, login=login)
    w.start()
    try:
        task_created = threading.Event()
        release_publish = threading.Event()

        def _delayed_create_task(coro):
            task = asyncio.ensure_future(coro)
            task_created.set()
            release_publish.wait(timeout=5.0)
            return task

        w._create_task = _delayed_create_task
        assert w.request_login(OUJDA) is True
        _wait(task_created)
        # cancel_account runs EXACTLY in the gap between task creation and
        # its publication as _active_task.
        w.cancel_account(OUJDA)
        release_publish.set()
        assert _wait_until(lambda: OUJDA not in w._pending_or_active_accounts)
        assert login.for_account(OUJDA).calls == []  # the coroutine body never ran at all
        assert manager.state_of(OUJDA) not in (AccountState.READY, AccountState.ERROR)
    finally:
        assert w.stop(timeout=2.0) is True


def test_rapid_login_then_immediate_cancel_never_corrupts_state():
    """Stress regression for the same race: request+cancel back-to-back,
    many times, so any iteration where the dispatch loop had already
    dequeued and created the task before cancel_account's generation bump
    is exercised many times over. Whatever happened, the account must
    remain perfectly usable and never end up incorrectly READY/ERROR."""
    login = OperationRouter()
    manager = _authorized_manager()
    w = _worker(manager=manager, login=login)
    w.start()
    try:
        for _ in range(300):
            assert w.request_login(OUJDA) is True
            w.cancel_account(OUJDA)
            assert _wait_until(lambda: OUJDA not in w._pending_or_active_accounts, timeout=1.0)
        assert manager.state_of(OUJDA) not in (AccountState.READY, AccountState.ERROR)
        assert w.request_login(OUJDA) is True
        _wait(login.for_account(OUJDA).finished)  # not held -- completes on its own
    finally:
        assert w.stop(timeout=2.0) is True


# --------------------------------------------------------------------- #
# Pass 3B correction, finding 5 -- authorization rechecked at FINAL task
# publication (not just generation), deterministic barrier
# --------------------------------------------------------------------- #


def test_removal_between_precheck_and_publication_prevents_coroutine_from_running():
    """Removes the account (via reconcile_allowed_accounts -- generation is
    untouched, only authorization changes) EXACTLY in the gap between task
    creation and its publication as _active_task. The final publication
    check must also validate authorization, not only generation, so the
    coroutine body must never run."""
    login = OperationRouter()
    manager = _authorized_manager()
    w = _worker(manager=manager, login=login)
    w.start()
    try:
        task_created = threading.Event()
        release_publish = threading.Event()

        def _delayed_create_task(coro):
            task = asyncio.ensure_future(coro)
            task_created.set()
            release_publish.wait(timeout=5.0)
            return task

        w._create_task = _delayed_create_task
        assert w.request_login(OUJDA) is True
        _wait(task_created)
        manager.reconcile_allowed_accounts(())  # removed -- generation untouched
        release_publish.set()
        assert _wait_until(lambda: OUJDA not in w._pending_or_active_accounts)
        assert login.for_account(OUJDA).calls == []  # the coroutine body never ran at all
    finally:
        assert w.stop(timeout=2.0) is True


# --------------------------------------------------------------------- #
# Finding 4 -- persistence mutations coordinated with cancellation
# --------------------------------------------------------------------- #


def test_A_stale_login_save_cannot_recreate_session_after_cancellation_wins():
    login = OperationRouter()
    store = BlockingSessionStore().block_save()
    manager = _authorized_manager()
    material = FakeSessionMaterial(
        {"cookies": [{"name": "new", "value": "session", "domain": "d", "path": "/"}], "origins": []},
    )
    login.for_account(OUJDA).result = material
    w = _worker(manager=manager, store=store, login=login)
    w.start()
    try:
        assert w.request_login(OUJDA) is True
        _wait(login.for_account(OUJDA).finished)  # perform_manual_login itself completes quickly
        _wait(store.save_entered)  # now blocked INSIDE store.save()'s critical section

        cancel_done = threading.Event()

        def _cancel():
            w.cancel_account(OUJDA)
            cancel_done.set()

        cancel_thread = threading.Thread(target=_cancel)
        cancel_thread.start()
        try:
            # cancel_account must NOT return while the old save can still
            # complete -- save() itself hasn't recorded the call yet either,
            # since it only does so AFTER save_release unblocks it.
            assert cancel_done.wait(timeout=0.2) is False
            assert store.save_calls == []
        finally:
            store.save_release.set()  # never leave anything blocked, even on assertion failure
        cancel_thread.join(timeout=2.0)
        assert cancel_done.is_set()
        assert store.save_calls == [OUJDA]  # the old save DID complete

        # The write already landed (the local operation was allowed to
        # finish), but the worker itself must never have reported READY --
        # the generation was bumped before cancel_account waited on it.
        assert manager.state_of(OUJDA) is not AccountState.READY

        # Once cancel_account has returned, the controller can safely clear
        # the account, and nothing stale can undo that afterward.
        store.clear(OUJDA)
        assert store.load(OUJDA) is None
    finally:
        assert w.stop(timeout=2.0) is True


def test_B_stale_logout_clear_cannot_delete_a_newer_session_after_cancellation_wins():
    verify = OperationRouter()
    store = BlockingSessionStore({OUJDA: {"cookies": [], "origins": []}}).block_clear()
    manager = _authorized_manager(saved=(OUJDA,))
    verify.for_account(OUJDA).result = "LOGGED_OUT"
    w = _worker(manager=manager, store=store, verify=verify)
    w.start()
    try:
        assert w.request_verification(OUJDA) is True
        _wait(verify.for_account(OUJDA).finished)
        _wait(store.clear_entered)  # blocked INSIDE store.clear()'s critical section

        cancel_done = threading.Event()

        def _cancel():
            w.cancel_account(OUJDA)
            cancel_done.set()

        cancel_thread = threading.Thread(target=_cancel)
        cancel_thread.start()
        try:
            assert cancel_done.wait(timeout=0.2) is False
            assert store.clear_calls == []
        finally:
            store.clear_release.set()  # never leave anything blocked, even on assertion failure
        cancel_thread.join(timeout=2.0)
        assert cancel_done.is_set()
        assert store.clear_calls == [OUJDA]  # the old clear DID complete

        assert manager.state_of(OUJDA) is not AccountState.LOGIN_REQUIRED

        # After cancel_account has returned, a NEWER session can be
        # installed -- the old (already-completed) clear cannot delete it.
        newer_session = {"cookies": [{"name": "new", "value": "session2", "domain": "d", "path": "/"}], "origins": []}
        store.save(OUJDA, newer_session)
        assert store.load(OUJDA) == newer_session
    finally:
        assert w.stop(timeout=2.0) is True


def test_C_stop_timeout_while_persistence_mutation_blocked_then_succeeds():
    login = OperationRouter()
    store = BlockingSessionStore().block_save()
    manager = _authorized_manager()
    login.for_account(OUJDA).result = FakeSessionMaterial({"cookies": [], "origins": []})
    w = _worker(manager=manager, store=store, login=login)
    w.start()
    try:
        assert w.request_login(OUJDA) is True
        _wait(store.save_entered)
        assert w.stop(timeout=0.1) is False
        assert w.is_alive() is True
    finally:
        store.save_release.set()  # never leave anything blocked, even on assertion failure
        assert w.stop(timeout=2.0) is True
        assert w.is_alive() is False


# --------------------------------------------------------------------- #
# Finding 5 -- session_store.load() failures handled safely
# --------------------------------------------------------------------- #


def test_load_exception_is_handled_safely_and_dispatcher_stays_alive():
    verify = OperationRouter()
    store = FailOnceLoadStore({OUJDA: {"cookies": [], "origins": []}})
    store.fail_load_once(OUJDA, RuntimeError(f"disk read failed {MARKER}"))
    manager = _authorized_manager(accounts=(OUJDA,))
    manager.record_probe_outcome(OUJDA, ProbeOutcome.AUTHENTICATED)  # force READY first
    updates: list[tuple] = []
    w = _worker(manager=manager, store=store, verify=verify, on_update=lambda *a: updates.append(a))
    w.start()
    try:
        assert manager.state_of(OUJDA) is AccountState.READY
        assert w.request_verification(OUJDA) is True
        assert _wait_until(lambda: manager.state_of(OUJDA) is AccountState.ERROR)
        assert verify.for_account(OUJDA).calls == []  # portal op never invoked

        for call in updates:
            assert call == ()  # payload-free -- structurally cannot carry the marker

        # dispatcher stays alive -- a second verification (now succeeding,
        # since fail_load_once only fires once) still executes correctly.
        verify.for_account(OUJDA).result = "AUTHENTICATED"
        assert w.request_verification(OUJDA) is True
        _wait(verify.for_account(OUJDA).finished)
        assert _wait_until(lambda: manager.state_of(OUJDA) is AccountState.READY)
        assert w.is_alive() is True
    finally:
        assert w.stop(timeout=2.0) is True


# --------------------------------------------------------------------- #
# Finding 6 -- no stale update callback for a removed account
# --------------------------------------------------------------------- #


def test_removal_race_login_result_produces_no_stale_callback():
    login = OperationRouter()
    manager = _authorized_manager()
    op = login.for_account(OUJDA).hold()
    op.result = FakeSessionMaterial({"cookies": [], "origins": []})
    updates: list[tuple] = []
    w = _worker(manager=manager, login=login, on_update=lambda *a: updates.append(a))
    w.start()
    try:
        assert w.request_login(OUJDA) is True
        _wait(op.started)
        manager.reconcile_allowed_accounts(())  # OUJDA removed mid-flight
        op.release()
        _wait(op.finished)
        time.sleep(0.05)  # let the (discarded) result-application path run
        assert manager.is_authorized(OUJDA) is False
        assert manager.state_of(OUJDA) is None
        assert updates == []
    finally:
        assert w.stop(timeout=2.0) is True


def test_removal_race_verification_result_produces_no_stale_callback():
    verify = OperationRouter()
    store = FakeSessionStore({OUJDA: {"cookies": [], "origins": []}})
    manager = _authorized_manager(saved=(OUJDA,))
    op = verify.for_account(OUJDA).hold()
    op.result = "AUTHENTICATED"
    updates: list[tuple] = []
    w = _worker(manager=manager, store=store, verify=verify, on_update=lambda *a: updates.append(a))
    w.start()
    try:
        assert w.request_verification(OUJDA) is True
        _wait(op.started)
        manager.reconcile_allowed_accounts(())
        op.release()
        _wait(op.finished)
        time.sleep(0.05)
        assert manager.state_of(OUJDA) is None
        assert updates == []
    finally:
        assert w.stop(timeout=2.0) is True


# --------------------------------------------------------------------- #
# Pass 3B correction, finding 4 -- deterministic pause BETWEEN a successful
# manager transition and callback publication, proving the payload-free
# design cannot leak a removed account's state through the callback
# --------------------------------------------------------------------- #


def test_pause_between_transition_and_callback_removal_carries_no_stale_state():
    login = OperationRouter()
    manager = _authorized_manager()
    login.for_account(OUJDA).result = FakeSessionMaterial({"cookies": [], "origins": []})
    updates: list[tuple] = []
    w = _worker(manager=manager, login=login, on_update=lambda *a: updates.append(a))
    w.start()

    paused = threading.Event()
    release = threading.Event()

    def _pause_hook():
        paused.set()
        release.wait(timeout=5.0)

    w._before_emit = _pause_hook

    try:
        assert w.request_login(OUJDA) is True
        _wait(paused)  # record_login_success has ALREADY applied -- callback not yet published
        assert manager.state_of(OUJDA) is AccountState.READY  # the transition genuinely happened
        manager.reconcile_allowed_accounts(())  # remove the account NOW, before the callback fires
        release.set()

        # Bounded settle so the (now-firing) callback has a chance to run.
        assert _wait_until(lambda: len(updates) > 0)

        for call in updates:
            assert call == ()  # payload-free -- structurally cannot carry the removed account/state

        assert manager.tracked_account_ids() == ()  # the authoritative snapshot has no removed account
        assert manager.state_of(OUJDA) is None
        assert w.is_alive() is True
    finally:
        assert w.stop(timeout=2.0) is True
