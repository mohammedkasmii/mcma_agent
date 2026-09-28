"""mcma.app.workstation_runner.browser_worker -- the dedicated non-daemon
thread + private asyncio event loop that serializes local browser-session
operations (Phase 1B-B Pass 3A, hardened by two rounds of concurrency
correction): manual MCMA login, saved-session verification, cancellation,
and bounded shutdown.

Not wired into the controller or GUI yet -- this module is the worker
alone.

Dependency boundary (enforced by tests/app/workstation_runner/
test_import_isolation.py and tests/contracts/test_import_boundaries.py):
this module imports NO Playwright, NO mcma.portal, NO tkinter, NO HTTP
client, NO persistence/SQLite, NO FastAPI, and NO writer/form-filling
code. The portal operations, the session store, and the session manager
are all accepted through narrow injected callables/protocols -- this
module never imports a concrete portal class and never knows what a
Playwright object looks like.

Two separate locks, two separate concerns -- never nested/acquired inside
one another, so there is no lock-ordering deadlock risk:
  * `_lock` -- guards ALL command-admission and generation bookkeeping
    (`_stopping`, `_pending_or_active_accounts`, `_login_account_id`,
    `_generation`, `_active_task`, `_active_account_id`). This is the ONE
    linearization point for shutdown: stop() closes admission (sets
    `_stopping = True` and bumps every pending/active account's
    generation) in a SINGLE critical section under this lock, and
    request_login/request_verification re-check `_stopping` inside that
    SAME lock as part of their own accept-and-register critical section.
    Whichever side's critical section runs first is authoritative; there
    is no window in between where a request can be admitted after
    shutdown has closed admission. cancel_account's generation bump uses
    this same lock too, which is what lets the dispatch loop's
    generation+authorization recheck (right before publishing a task as
    active) never race a concurrent cancel_account.
  * `_persistence_lock` -- a barrier around session_store.save()/clear().
    The mutation always revalidates the generation from INSIDE this lock
    before ever touching the store; cancel_account acquires-and-releases
    the SAME lock (after bumping the generation) purely to WAIT for an
    already-in-progress mutation to finish. Whichever of "revalidate+
    mutate" or "bump+wait" reaches the lock first, the other one always
    observes a result consistent with cancellation having already
    happened -- so once cancel_account() returns, no command from the
    cancelled generation can still save or clear that account's session.

Thread/loop LIFECYCLE fields (`_lifecycle_state`, `_thread`, `_loop`,
`_queue`, `_stop_requested_before_loop`) are guarded by their own
`_lifecycle_lock`, entirely separate from admission -- see start()/stop()
for exactly how the two are sequenced without ever nesting the locks.

The update callback (`on_update`) is a payload-free `Callable[[], None]`
change signal, never account_id/state -- see _emit()'s docstring for why.
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from enum import Enum
from typing import Awaitable, Callable, Protocol

from mcma.app.workstation_runner.protocol import RUNNER_ACCOUNT_IDS
from mcma.app.workstation_runner.sessions import ProbeOutcome, WorkstationSessionManager

_LOOP_READY_TIMEOUT_SECONDS = 5.0


class SessionStoreProtocol(Protocol):
    """Structural -- satisfied by WorkstationSessionStore without this
    module ever importing it (or mcma.portal's DPAPI-adjacent internals)."""

    def load(self, account_id: str) -> dict | None: ...
    def save(self, account_id: str, storage_state: dict) -> None: ...
    def clear(self, account_id: str) -> None: ...


class SessionMaterialLike(Protocol):
    """Structural -- satisfied by mcma.portal.capabilities.SessionMaterial
    without this module ever importing it. consume_for_handoff() is called
    exactly once, exactly as that class's own contract requires."""

    def consume_for_handoff(self) -> dict: ...


# The injected async portal operations. Neither is imported from
# mcma.portal -- both are accepted as plain callables returning an
# awaitable, and their RESULTS are handled structurally:
#   * a successful login result exposes .consume_for_handoff() exactly
#     once (mcma.portal.capabilities.SessionMaterial's own contract);
#   * a verification result is treated as an Enum-or-str whose .value (or
#     the value itself) is one of "AUTHENTICATED" / "LOGGED_OUT" /
#     "INDETERMINATE" -- exactly mcma.portal.workstation_sessions.
#     SessionProbeOutcome's members, without importing that enum.
PerformManualLogin = Callable[[str], Awaitable[SessionMaterialLike]]
VerifySavedSession = Callable[[str, dict], Awaitable[object]]

# Payload-free: a pure "something may have changed" signal. See _emit()'s
# docstring for why this can never carry account_id/AccountState.
OnUpdate = Callable[[], None]


class BrowserWorkerStartupFailed(Exception):
    """Raised by start() when the worker's thread/event loop could not be
    brought up: event-loop construction failed, threading.Thread.start()
    itself failed, or the loop never signalled readiness within the
    bounded timeout. Fixed, safe message only -- never the underlying
    exception's text, a credential, a filesystem path, or portal data.
    By the time this is raised, the worker's thread (if one was ever
    created) has already been confirmed fully stopped -- start() never
    returns or raises while a failed startup's thread is still alive."""

    def __init__(self) -> None:
        super().__init__("the workstation browser session worker failed to start")


class _CommandKind(Enum):
    LOGIN = "LOGIN"
    VERIFY = "VERIFY"


@dataclass(frozen=True)
class _Command:
    kind: _CommandKind
    account_id: str
    generation: int


class _LifecycleState(Enum):
    NOT_STARTED = "NOT_STARTED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"


class BrowserSessionWorker:
    """Owns one non-daemon thread and one private asyncio event loop.
    Public methods (request_login, request_verification, cancel_account,
    stop, is_alive) are all thread-safe and callable from any thread,
    including the Tk main thread -- none of them ever await anything, and
    none of them (except stop()'s bounded thread.join()) ever block for an
    unbounded amount of time."""

    def __init__(
        self,
        *,
        session_manager: WorkstationSessionManager,
        session_store: SessionStoreProtocol,
        perform_manual_login: PerformManualLogin,
        verify_saved_session: VerifySavedSession,
        on_update: OnUpdate | None = None,
    ) -> None:
        self._session_manager = session_manager
        self._session_store = session_store
        self._perform_manual_login = perform_manual_login
        self._verify_saved_session = verify_saved_session
        self._on_update = on_update

        # Command admission + generation bookkeeping -- see the module
        # docstring for why this is the single shutdown linearization point.
        self._lock = threading.Lock()
        self._stopping = False
        self._pending_or_active_accounts: set[str] = set()
        self._login_account_id: str | None = None
        self._generation: dict[str, int] = {}
        self._active_task: asyncio.Task | None = None
        self._active_account_id: str | None = None

        self._persistence_lock = threading.Lock()

        # Thread/loop lifecycle bookkeeping -- a separate concern, guarded
        # by its own lock, never nested with the two above.
        self._lifecycle_lock = threading.Lock()
        self._lifecycle_state = _LifecycleState.NOT_STARTED
        self._loop_ready = threading.Event()
        self._stop_requested_before_loop = False
        self._startup_failed = False
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._queue: "asyncio.Queue[_Command | None] | None" = None

    # ------------------------------------------------------------- #
    # Lifecycle
    # ------------------------------------------------------------- #

    def start(self) -> None:
        """Idempotent and race-safe: concurrent duplicate start() calls
        create AT MOST ONE thread. Once stop() has begun or completed
        (STOPPING/STOPPED), start() creates no thread at all -- a stopped
        worker stays stopped.

        A successful return only ever happens after the event loop and
        queue are initialized AND the worker thread is confirmed alive and
        running the dispatch loop. On any failure to reach that state --
        threading.Thread.start() itself raising, event-loop construction
        failing inside the thread, or the readiness wait timing out -- this
        method NEVER returns while that thread might still be alive or
        mid-teardown: it always performs a bounded stop()/join() first (or,
        for a Thread.start() failure, there is no thread to join at all),
        THEN raises BrowserWorkerStartupFailed."""
        with self._lifecycle_lock:
            if self._lifecycle_state is _LifecycleState.NOT_STARTED:
                self._lifecycle_state = _LifecycleState.STARTING
                thread = threading.Thread(
                    target=self._run_loop, name="mcma-runner-browser-worker", daemon=False,
                )
                # Publish BEFORE starting the OS thread, and both under
                # this same lock stop() reads through -- a concurrent
                # stop() can therefore never observe "no thread" once this
                # method has decided to create one.
                self._thread = thread
                try:
                    thread.start()
                except Exception:
                    # threading.Thread.start() itself failed -- no OS
                    # thread was ever created, so there is nothing to join
                    # and nothing left alive. Restore a truthful terminal
                    # state immediately.
                    self._lifecycle_state = _LifecycleState.STOPPED
                    self._thread = None
                    raise BrowserWorkerStartupFailed() from None
                should_wait = True
            elif self._lifecycle_state is _LifecycleState.STARTING:
                should_wait = True
            elif self._lifecycle_state is _LifecycleState.RUNNING:
                should_wait = False  # already fully up -- nothing to wait for
            else:
                return  # STOPPING or STOPPED -- never create a thread again
        if not should_wait:
            return

        ready = self._loop_ready.wait(timeout=_LOOP_READY_TIMEOUT_SECONDS)
        with self._lifecycle_lock:
            construction_failed = self._startup_failed
            # STARTING or RUNNING both mean "still successfully up" here --
            # with several concurrent start() callers all waiting on the
            # SAME thread, only the first to reach this check ever actually
            # observes STARTING and performs the STARTING->RUNNING
            # transition; every other caller observes RUNNING (already
            # declared) a moment later. Treating RUNNING as failure here
            # would make every concurrent duplicate start() incorrectly
            # stop an otherwise perfectly healthy worker.
            state = self._lifecycle_state
            clean_success = ready and not construction_failed and state in (
                _LifecycleState.STARTING, _LifecycleState.RUNNING,
            )
            if clean_success and state is _LifecycleState.STARTING:
                self._lifecycle_state = _LifecycleState.RUNNING
        if clean_success:
            return

        # Not a clean success: readiness timed out, construction failed
        # inside _run_loop, or a concurrent stop() has already taken this
        # worker over. In EVERY case, never trust `_loop_ready` alone as
        # proof the OS thread has actually finished (it is set from INSIDE
        # the thread, strictly before that thread's own teardown
        # completes) -- stop() performs the one reliable, bounded
        # thread.join() that guarantees this.
        self.stop(timeout=_LOOP_READY_TIMEOUT_SECONDS)
        if construction_failed or not ready:
            raise BrowserWorkerStartupFailed()
        # else: a concurrent stop() legitimately won the race before this
        # start() could declare success -- not a startup fault, so no
        # exception; the worker is simply (correctly) stopped.

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def stop(self, timeout: float) -> bool:
        """Never returns True while a worker thread started by this
        object is alive. The single stop linearization point: closes
        request admission (`_stopping = True`) and invalidates every
        currently queued-or-active account's generation atomically, in
        ONE critical section under `_lock` -- the SAME lock
        request_login/request_verification use for their own accept step.
        Only after that closes does this method touch lifecycle/loop
        state or perform the bounded, lock-free thread.join(). Safe to
        call repeatedly, before start(), and concurrently with start()."""
        with self._lock:
            if not self._stopping:
                self._stopping = True
                for account_id in self._pending_or_active_accounts:
                    self._generation[account_id] = self._generation.get(account_id, 0) + 1
        self._after_admission_closed()

        with self._lifecycle_lock:
            if self._lifecycle_state is _LifecycleState.NOT_STARTED:
                self._lifecycle_state = _LifecycleState.STOPPED
                return True
            if self._lifecycle_state is _LifecycleState.STOPPED:
                return True
            self._lifecycle_state = _LifecycleState.STOPPING
            thread = self._thread
            loop = self._loop
            if loop is None:
                # The loop does not exist yet (start() is still inside
                # _run_loop's construction, or never got that far) --
                # _run_loop itself checks this flag the moment the loop
                # DOES exist and terminates immediately instead of ever
                # entering the dispatch loop.
                self._stop_requested_before_loop = True
        if loop is not None:
            try:
                loop.call_soon_threadsafe(self._request_stop)
            except RuntimeError:
                pass  # loop already closing/closed -- thread is on its way out regardless
        if thread is not None:
            thread.join(timeout=timeout)
        stopped = thread is None or not thread.is_alive()
        if stopped:
            with self._lifecycle_lock:
                self._lifecycle_state = _LifecycleState.STOPPED
        return stopped

    def _after_admission_closed(self) -> None:
        """No-op production hook. Tests may override this on an instance
        to deterministically pause stop() immediately after shutdown
        admission has been closed (the exact linearization point) and
        before any lifecycle/loop work runs."""
        return None

    def _request_stop(self) -> None:
        """Runs ON the loop thread (scheduled via call_soon_threadsafe --
        the only thread-safe way to touch a Task or an asyncio.Queue that
        belongs to another thread's loop)."""
        if self._active_task is not None:
            self._active_task.cancel()
        if self._queue is not None:
            self._queue.put_nowait(None)

    @staticmethod
    def _new_event_loop() -> asyncio.AbstractEventLoop:
        """A tiny, deliberately overridable seam (an instance can shadow
        this with a plain attribute) so tests can deterministically delay
        or fail loop construction -- production behavior is exactly
        asyncio.new_event_loop()."""
        return asyncio.new_event_loop()

    @staticmethod
    def _create_task(coro) -> "asyncio.Task":
        """A tiny, deliberately overridable seam (mirrors _new_event_loop)
        so tests can deterministically widen the window between task
        creation and its publication as _active_task, to exercise
        cancel_account's / reconcile_allowed_accounts's coordination with
        that gap. Production behavior is exactly asyncio.ensure_future(coro)."""
        return asyncio.ensure_future(coro)

    def _run_loop(self) -> None:
        try:
            loop = self._new_event_loop()
            asyncio.set_event_loop(loop)
            queue: "asyncio.Queue[_Command | None]" = asyncio.Queue()
        except Exception:
            # Loop construction itself failed. Deliberately do NOT
            # transition _lifecycle_state to STOPPED here -- this method
            # runs ON the worker thread itself, strictly BEFORE that
            # thread's own teardown completes, and stop() treats STOPPED
            # as "already fully confirmed stopped", skipping its own
            # thread.join(). Self-declaring STOPPED from inside the very
            # thread that has not finished yet would reproduce the exact
            # bug this correction fixes, just relocated. _lifecycle_state
            # is left as STARTING; only stop() (called by start()'s own
            # failure path below) may ever transition to STOPPED, and only
            # after its own thread.join() has confirmed the thread is
            # truly done. `_startup_failed` is what lets start() tell
            # "genuine construction failure" apart from every other reason
            # `_loop_ready` might fire.
            with self._lifecycle_lock:
                self._startup_failed = True
            self._loop_ready.set()
            return
        with self._lifecycle_lock:
            self._queue = queue
            self._loop = loop
            stop_already_requested = self._stop_requested_before_loop
        self._loop_ready.set()
        try:
            if stop_already_requested:
                return  # a stop() arrived before the loop existed -- run nothing
            loop.run_until_complete(self._dispatch_loop())
        finally:
            # The dispatch loop only returns once any active command's
            # task has been fully awaited (including its own cancellation
            # cleanup) -- see _dispatch_loop -- so no browser coroutine or
            # pending task is ever abandoned by closing the loop here.
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
            except Exception:
                pass
            loop.close()

    async def _dispatch_loop(self) -> None:
        assert self._queue is not None
        while True:
            command = await self._queue.get()
            if command is None:
                return
            if not self._is_launchable(command.account_id, command.generation):
                # Cancelled or superseded while still queued -- never
                # launches a browser operation for it at all.
                self._finish_command(command.account_id)
                continue
            if command.kind is _CommandKind.LOGIN:
                coro = self._execute_login(command.account_id, command.generation)
            else:
                coro = self._execute_verify(command.account_id, command.generation)
            task = self._create_task(coro)
            # Task creation schedules the coroutine's first step but does
            # NOT run any of its body yet (nothing has been awaited on this
            # thread since task creation). Publishing _active_task, AND
            # the FINAL generation+authorization recheck, happen in ONE
            # lock section here -- the SAME lock cancel_account() uses --
            # so neither cancel_account() nor a concurrent
            # reconcile_allowed_accounts() removal can be missed in the
            # gap between "task created" and "task published".
            with self._lock:
                if self._generation.get(command.account_id, 0) != command.generation:
                    published = False
                elif not self._session_manager.is_authorized(command.account_id):
                    published = False
                else:
                    self._active_task = task
                    self._active_account_id = command.account_id
                    published = True
            if not published:
                # The coroutine body must never run: cancel it before it
                # ever gets a chance to invoke the portal operation, touch
                # the store, or emit an update. Task.cancel() on a task
                # that has not yet started throws CancelledError into it
                # at its very first step -- the coroutine's own body is
                # never entered, and awaiting the task below both consumes
                # that CancelledError cleanly and closes the underlying
                # coroutine object (no "coroutine was never awaited"
                # warning).
                task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass  # cooperative cancellation already unwound cleanly inside _execute_*
            finally:
                with self._lock:
                    self._active_task = None
                    self._active_account_id = None
                self._finish_command(command.account_id)

    # ------------------------------------------------------------- #
    # Public requests -- thread-safe, never block on browser I/O
    # ------------------------------------------------------------- #

    def request_login(self, account_id: str) -> bool:
        if account_id not in RUNNER_ACCOUNT_IDS:
            return False
        if not self._session_manager.is_authorized(account_id):
            return False
        with self._lock:
            if self._stopping:
                return False  # rechecked under the SAME lock stop() uses -- see module docstring
            if account_id in self._pending_or_active_accounts or self._login_account_id is not None:
                return False  # duplicate for this account, or another login already in flight
            generation = self._generation.get(account_id, 0)
            self._pending_or_active_accounts.add(account_id)
            self._login_account_id = account_id
            accepted = self._enqueue_locked(_Command(_CommandKind.LOGIN, account_id, generation))
            if not accepted:
                # The loop was closing between our stop-check and the
                # actual enqueue -- roll back every bit of bookkeeping so
                # this account is immediately requestable again, and never
                # claim acceptance for work that will never run.
                self._pending_or_active_accounts.discard(account_id)
                self._login_account_id = None
            return accepted

    def request_verification(self, account_id: str) -> bool:
        if account_id not in RUNNER_ACCOUNT_IDS:
            return False
        if not self._session_manager.is_authorized(account_id):
            return False
        with self._lock:
            if self._stopping:
                return False
            if account_id in self._pending_or_active_accounts:
                return False  # duplicate verification, or overlapping login for this account
            generation = self._generation.get(account_id, 0)
            self._pending_or_active_accounts.add(account_id)
            accepted = self._enqueue_locked(_Command(_CommandKind.VERIFY, account_id, generation))
            if not accepted:
                self._pending_or_active_accounts.discard(account_id)
            return accepted

    def _enqueue_locked(self, command: _Command) -> bool:
        """Must be called while already holding self._lock. Never lets a
        RuntimeError from a closing/closed loop escape to the caller (the
        GUI thread) -- returns False instead, so the caller rolls back its
        own bookkeeping."""
        loop, queue = self._loop, self._queue
        if loop is None or queue is None:
            return False
        try:
            loop.call_soon_threadsafe(queue.put_nowait, command)
            return True
        except RuntimeError:
            return False

    def cancel_account(self, account_id: str) -> None:
        """Invalidates any queued-but-not-started command for this account
        (via the generation bump) and, if this account's command is the
        one currently executing, cancels its task through the loop's own
        thread-safe scheduling mechanism.

        Also acts as a PERSISTENCE BARRIER: after bumping the generation,
        it acquires-and-releases `_persistence_lock` before returning. Any
        session_store.save()/clear() call always revalidates the
        generation from INSIDE that same lock immediately before mutating
        -- so by the time this method returns, either that mutation had
        already completed (harmlessly, under the OLD still-valid
        generation, before the bump) or it will see the bumped generation
        and never touch the store at all. Either way, the caller may
        safely clear or replace this account's session the moment this
        method returns, knowing no stale work can mutate it afterward."""
        with self._lock:
            self._generation[account_id] = self._generation.get(account_id, 0) + 1
            active_task = self._active_task if self._active_account_id == account_id else None
            loop = self._loop
        with self._persistence_lock:
            pass  # pure barrier -- see docstring
        if active_task is not None and loop is not None:
            loop.call_soon_threadsafe(active_task.cancel)

    def _finish_command(self, account_id: str) -> None:
        with self._lock:
            self._pending_or_active_accounts.discard(account_id)
            if self._login_account_id == account_id:
                self._login_account_id = None

    def _is_launchable(self, account_id: str, generation: int) -> bool:
        """Combined generation+authorization gate used to decide whether
        to even CREATE a task for this command. The dispatch loop performs
        a SECOND, final combined check (also generation+authorization,
        atomically with publication) immediately before letting the
        coroutine actually run -- see _dispatch_loop. This first check
        exists purely to avoid creating (and then immediately discarding)
        a task for a command that is already known-stale."""
        if not self._generation_matches(account_id, generation):
            return False
        return self._session_manager.is_authorized(account_id)

    def _generation_matches(self, account_id: str, generation: int) -> bool:
        with self._lock:
            return self._generation.get(account_id, 0) == generation

    def _before_emit(self) -> None:
        """No-op production hook. Tests may override this on an instance
        to deterministically pause between a manager transition being
        applied and the update callback being published."""
        return None

    def _emit(self) -> None:
        """The update callback is a payload-free change signal by design:
        it is fired AFTER a WorkstationSessionManager.record_* call has
        already returned True (the transition was atomically applied), but
        the account could still be removed a moment later, before this
        callback actually runs -- there is no way to hand the caller an
        account_id/AccountState pair here that is guaranteed still current
        by the time they read it. Rather than chase that residual race
        with more locking, the callback carries NOTHING: the future
        controller reacts to it by reading a FRESH, authoritative snapshot
        from WorkstationSessionManager (snapshot()/state_of()/
        is_authorized()) -- a delayed or even spurious notification is
        completely harmless, because it can never carry stale state, only
        prompt a fresh read of state that is authoritative at read time.

        Never called while holding _lock or _persistence_lock -- a slow or
        misbehaving callback must never block command admission or a
        persistence mutation."""
        self._before_emit()
        if self._on_update is not None:
            try:
                self._on_update()
            except Exception:
                pass  # a callback failure must never break the worker loop

    # ------------------------------------------------------------- #
    # Command execution -- runs on the loop thread only
    # ------------------------------------------------------------- #

    async def _execute_login(self, account_id: str, generation: int) -> None:
        """Ordering, test-proven: positively authenticated material ->
        encrypted store save succeeds -> READY. Never the reverse. The
        save itself is a persistence-barrier mutation (see cancel_account's
        docstring): it revalidates the generation from inside
        `_persistence_lock`, and the account_id is only ever reported
        READY via WorkstationSessionManager.record_login_success's own
        atomic (still-authorized?) check -- closing the residual gap
        between "we decided to apply this result" and "the account was
        removed a moment before we actually did"."""
        try:
            material = await self._perform_manual_login(account_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            # The login ATTEMPT itself did not succeed -- a timeout, the
            # employee closing the window, a probe failure, or any other
            # reason the portal adapter reports. Nothing NEW is known, so
            # the account's prior state is left exactly as it was: no
            # store write, no READY, and no ERROR transition either.
            return
        try:
            storage_state = material.consume_for_handoff()
        except asyncio.CancelledError:
            raise
        except Exception:
            if self._generation_matches(account_id, generation):
                if self._session_manager.record_operation_error(account_id):
                    self._emit()
            return

        saved = False
        save_failed = False
        with self._persistence_lock:
            if not self._generation_matches(account_id, generation):
                return  # cancelled/superseded while we held positive material -- never mutate
            try:
                self._session_store.save(account_id, storage_state)
                saved = True
            except Exception:
                save_failed = True
        if save_failed:
            # We HELD positive material and failed to persist it -- a
            # genuine operational fault. The store's own atomic-replace
            # contract already guarantees the previous encrypted session
            # (if any) was left untouched by the failed save.
            if self._generation_matches(account_id, generation):
                if self._session_manager.record_operation_error(account_id):
                    self._emit()
            return
        if saved and self._generation_matches(account_id, generation):
            if self._session_manager.record_login_success(account_id):
                self._emit()

    async def _execute_verify(self, account_id: str, generation: int) -> None:
        try:
            storage_state = self._session_store.load(account_id)
        except Exception:
            # An unexpected load failure -- never call the portal
            # operation, never touch the store further (whatever is on
            # disk, valid or not, is left exactly as-is), and never expose
            # the exception's text anywhere.
            if self._generation_matches(account_id, generation):
                if self._session_manager.record_operation_error(account_id):
                    self._emit()
            return
        if storage_state is None:
            # No valid saved state (missing OR corrupt -- session_store.load
            # already treats both identically) -- the portal operation is
            # never launched, and the truthful result is NOT_CONFIGURED.
            if self._generation_matches(account_id, generation):
                if self._session_manager.record_missing_saved_session(account_id):
                    self._emit()
            return
        try:
            outcome = await self._verify_saved_session(account_id, storage_state)
        except asyncio.CancelledError:
            raise
        except Exception:
            # An operational exception -- not an ambiguous observation.
            # The stored session is left untouched; ProbeOutcome.ERROR is
            # documented as exactly "the result of verify_saved_session, or
            # an exception from it".
            if self._generation_matches(account_id, generation):
                if self._session_manager.record_probe_outcome(account_id, ProbeOutcome.ERROR):
                    self._emit()
            return

        outcome_value = getattr(outcome, "value", outcome)
        if outcome_value == "AUTHENTICATED":
            if self._generation_matches(account_id, generation):
                if self._session_manager.record_probe_outcome(account_id, ProbeOutcome.AUTHENTICATED):
                    self._emit()
            return
        if outcome_value == "LOGGED_OUT":
            cleared = False
            clear_failed = False
            with self._persistence_lock:
                if not self._generation_matches(account_id, generation):
                    return  # cancelled/superseded -- never mutate the store
                try:
                    self._session_store.clear(account_id)
                    cleared = True
                except Exception:
                    clear_failed = True
            if clear_failed:
                # Clearing the now-invalid session itself failed -- never
                # claim it was removed. ERROR, not a false LOGIN_REQUIRED.
                if self._generation_matches(account_id, generation):
                    if self._session_manager.record_probe_outcome(account_id, ProbeOutcome.ERROR):
                        self._emit()
                return
            if cleared and self._generation_matches(account_id, generation):
                if self._session_manager.record_probe_outcome(account_id, ProbeOutcome.LOGGED_OUT):
                    self._emit()
            return
        # INDETERMINATE, or any value this worker does not recognize --
        # fails safe to ERROR either way. The stored session is retained.
        if self._generation_matches(account_id, generation):
            if self._session_manager.record_probe_outcome(account_id, ProbeOutcome.INDETERMINATE):
                self._emit()
