"""mcma.app.workstation_runner.job_worker -- the dedicated polling worker
that drives one DRY_RUN job at a time through claim -> start -> execute ->
finish (Phase 1C-B, item D).

Dependency boundary (enforced by tests/app/workstation_runner/
test_import_isolation.py and tests/contracts/test_import_boundaries.py):
this module imports NO Playwright, NO mcma.portal, NO tkinter, NO
SQLite/FastAPI, and NO mcma.execution/mcma.persistence. The HTTP transport
(a RegistryHttpClient-shaped object) and the DRY_RUN executor (an
async run_dry_run_check-shaped callable) are both accepted as injected
callables/protocols -- this module never imports a concrete portal class
and never knows what a Playwright object looks like. Mirrors
mcma.app.workstation_runner.browser_worker's own import-isolation
discipline, but with a much simpler concurrency model: exactly one job
pipeline runs at a time, never several admitted concurrently, so there is
no command queue or generation-fencing admission system to build here --
mirrors mcma.app.workstation_runner.heartbeat's simple thread + sequential
loop shape instead, extended with ONE internal asyncio.run() per job so the
async executor and a concurrent lease-renewal task can run together.

One non-daemon OS thread only (JobPollingWorker owns it) -- the
asyncio.to_thread calls `run_dry_run_check`'s own injected portal callable
might make internally are mcma.portal's concern, not this module's, and
never change this accounting: this module itself starts exactly one
threading.Thread.

Claims no job while disconnected, shutting down, or before account
reconciliation has reported READY: `is_ready()` is checked (freshly, never
cached) before every claim attempt, and the stop_event is rechecked
immediately before start_job() is ever called -- a shutdown that lands in
that exact window releases the claim (RUNNER_SHUTDOWN) instead of starting
it. Once RUNNING, a shutdown is never handled with release() (the server
itself refuses to release a RUNNING assignment): the executor task is
cancelled and RUNNER_CANCELLED is reported to finish() instead -- the ONE
call this module ever makes after RUNNING besides periodic renewal."""

from __future__ import annotations

import asyncio
import contextlib
import threading
from enum import Enum
from typing import Awaitable, Callable, Optional, Protocol

_INITIAL_BACKOFF_SECONDS = 2.0
_MAX_BACKOFF_SECONDS = 60.0
_DEFAULT_POLL_INTERVAL_SECONDS = 5.0
_DEFAULT_RENEW_INTERVAL_SECONDS = 30.0
_SHUTDOWN_POLL_INTERVAL_SECONDS = 0.2


class LifecycleEvent(Enum):
    JOB_STARTED = "JOB_STARTED"
    JOB_SUCCEEDED = "JOB_SUCCEEDED"
    JOB_FAILED = "JOB_FAILED"
    CONNECTION_FAILED = "CONNECTION_FAILED"


class ClaimedJobLike(Protocol):
    job_id: str
    claim_token: str
    generation: int


class StartedJobLike(Protocol):
    status: str
    plan_hash: Optional[str]


class RegistryClientProtocol(Protocol):
    """Structural -- satisfied by
    mcma.app.workstation_runner.http_client.RegistryHttpClient without an
    import dependency on it (this module never constructs one; the
    composition root does)."""

    def claim_job(self, runner_secret: str) -> Optional[ClaimedJobLike]: ...

    def start_job(self, runner_secret: str, *, job_id: str, claim_token: str, generation: int) -> "StartedJobLike": ...

    def renew_job(self, runner_secret: str, *, job_id: str, claim_token: str, generation: int) -> None: ...

    def release_job(self, runner_secret: str, *, job_id: str, claim_token: str, generation: int, reason_code: str) -> None: ...

    def finish_job(self, runner_secret: str, *, job_id: str, claim_token: str, generation: int, result: str): ...

    def close(self) -> None: ...


# The async DRY_RUN executor -- structurally
# mcma.app.workstation_runner.dry_run_executor.run_dry_run_check, called
# with the SAME keyword shape via a caller-supplied closure so this module
# never has to know the executor's full parameter list (expected_plan_hash,
# session_store, workflow_registry, check_identity_read_only are all
# already bound by the composition root).
RunDryRunCheck = Callable[[ClaimedJobLike, str], Awaitable[str]]  # (claimed_job, plan_hash) -> FINISH_RESULTS member

OnEvent = Callable[[LifecycleEvent], None]


def _default_wait(event: threading.Event, timeout: float) -> bool:
    return event.wait(timeout)


class JobPollingLifecycle:
    """Owns the poll/claim/start/execute/finish network+execution loop
    only. `is_ready()` and `run_dry_run_check` are both called fresh every
    time -- never cached -- so a change in connection/READY state or a
    plan rebuilt from the latest claim always reflects the current truth."""

    def __init__(
        self,
        client: RegistryClientProtocol,
        run_dry_run_check: RunDryRunCheck,
        *,
        is_ready: Callable[[], bool] = lambda: False,
        on_event: OnEvent = lambda event: None,
        wait: Callable[[threading.Event, float], bool] = _default_wait,
        poll_interval_seconds: float = _DEFAULT_POLL_INTERVAL_SECONDS,
        renew_interval_seconds: float = _DEFAULT_RENEW_INTERVAL_SECONDS,
        shutdown_poll_interval_seconds: float = _SHUTDOWN_POLL_INTERVAL_SECONDS,
    ) -> None:
        self._client = client
        self._run_dry_run_check = run_dry_run_check
        self._is_ready = is_ready
        self._on_event = on_event
        self._wait = wait
        self._poll_interval_seconds = poll_interval_seconds
        self._renew_interval_seconds = renew_interval_seconds
        self._shutdown_poll_interval_seconds = shutdown_poll_interval_seconds

    def run_forever(self, runner_secret: str, stop_event: threading.Event) -> None:
        try:
            backoff = _INITIAL_BACKOFF_SECONDS
            while not stop_event.is_set():
                if not self._is_ready():
                    # Disconnected, shutting down, or no account reported
                    # READY yet -- never even attempts a claim.
                    if self._wait(stop_event, self._poll_interval_seconds):
                        return
                    continue
                try:
                    claimed = self._client.claim_job(runner_secret)
                except Exception:
                    # Any transport/protocol failure (connection,
                    # unauthorized, malformed envelope -- this module never
                    # inspects which) is bounded backoff, never a busy
                    # loop and never an uncaught exception killing the
                    # worker thread.
                    self._on_event(LifecycleEvent.CONNECTION_FAILED)
                    if self._wait(stop_event, backoff):
                        return
                    backoff = min(backoff * 2, _MAX_BACKOFF_SECONDS)
                    continue
                backoff = _INITIAL_BACKOFF_SECONDS
                if claimed is None:
                    if self._wait(stop_event, self._poll_interval_seconds):
                        return
                    continue
                if stop_event.is_set():
                    # Shutdown landed in the exact window between a
                    # successful claim and ever calling start_job() --
                    # release it (CLAIMED-only, never RUNNING) rather than
                    # starting new work after shutdown has begun.
                    self._safe_release(runner_secret, claimed)
                    return
                self._run_one_job(runner_secret, claimed, stop_event)
        finally:
            try:
                self._client.close()
            except Exception:
                pass

    def _safe_release(self, runner_secret: str, claimed: ClaimedJobLike) -> None:
        try:
            self._client.release_job(
                runner_secret, job_id=claimed.job_id, claim_token=claimed.claim_token,
                generation=claimed.generation, reason_code="RUNNER_SHUTDOWN",
            )
        except Exception:
            pass  # best-effort -- the claim fences itself via lease expiry either way

    def _run_one_job(self, runner_secret: str, claimed: ClaimedJobLike, stop_event: threading.Event) -> None:
        try:
            started = self._client.start_job(
                runner_secret, job_id=claimed.job_id, claim_token=claimed.claim_token, generation=claimed.generation,
            )
        except Exception:
            self._on_event(LifecycleEvent.CONNECTION_FAILED)
            return
        if started.status == "NEEDS_REVIEW":
            # The server already resolved this job through planning alone
            # -- no browser work, nothing further for this worker to do.
            return
        self._on_event(LifecycleEvent.JOB_STARTED)
        result = asyncio.run(self._run_and_renew(runner_secret, claimed, started, stop_event))
        try:
            self._client.finish_job(
                runner_secret, job_id=claimed.job_id, claim_token=claimed.claim_token,
                generation=claimed.generation, result=result,
            )
        except Exception:
            pass  # best-effort -- an expired/fenced assignment is the server's own truthful landing either way
        self._on_event(LifecycleEvent.JOB_SUCCEEDED if result == "IDENTITY_MATCHED" else LifecycleEvent.JOB_FAILED)

    async def _run_and_renew(self, runner_secret: str, claimed: ClaimedJobLike, started, stop_event: threading.Event) -> str:
        """Runs the executor and a periodic lease renewal CONCURRENTLY
        (mirrors mcma.execution.runner's own _heartbeat_forever-alongside-
        the-identity-check pattern), watching `stop_event` so a shutdown
        that lands while RUNNING cancels the executor and reports
        RUNNER_CANCELLED -- never release() (invalid on a RUNNING
        assignment) and never silently abandoning the job."""
        exec_task = asyncio.ensure_future(self._run_dry_run_check(claimed, started.plan_hash))
        renew_task = asyncio.ensure_future(self._renew_forever(runner_secret, claimed))
        try:
            while not exec_task.done():
                if stop_event.is_set():
                    exec_task.cancel()
                    break
                await asyncio.sleep(self._shutdown_poll_interval_seconds)
            try:
                return await exec_task
            except asyncio.CancelledError:
                return "RUNNER_CANCELLED"
        finally:
            renew_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await renew_task

    async def _renew_forever(self, runner_secret: str, claimed: ClaimedJobLike) -> None:
        try:
            while True:
                await asyncio.sleep(self._renew_interval_seconds)
                try:
                    await asyncio.to_thread(
                        self._client.renew_job, runner_secret, job_id=claimed.job_id,
                        claim_token=claimed.claim_token, generation=claimed.generation,
                    )
                except Exception:
                    pass  # best-effort -- a lost lease surfaces through finish_job's own outcome
        except asyncio.CancelledError:
            raise


class _WorkerLifecycleState(Enum):
    NOT_STARTED = "NOT_STARTED"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"


class JobPollingWorker:
    """Thread wrapper: AT MOST ONE non-daemon thread running one
    JobPollingLifecycle loop, ever, across any number of start() calls --
    release-blocker correction: start() used to create a new thread on
    EVERY call, with no lifecycle tracking at all.

    A single `_lock` is the ONE linearization point for both start() and
    stop() (mirrors mcma.app.workstation_runner.browser_worker.
    BrowserSessionWorker's own reasoning): whichever of the two reaches the
    lock first is authoritative, and Thread.start() itself runs INSIDE
    that same critical section (exactly like BrowserSessionWorker.start()
    does) -- so a concurrent stop() can never observe a Thread object that
    exists but has not actually been started yet (which would make its own
    join() raise), and can never race start() into creating a second
    thread. Once STOPPING or STOPPED, start() creates no thread at all --
    a stopped worker is never resurrected."""

    def __init__(self, lifecycle: JobPollingLifecycle, runner_secret: str) -> None:
        self._lifecycle = lifecycle
        self._runner_secret = runner_secret
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._state = _WorkerLifecycleState.NOT_STARTED
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Idempotent and race-safe: concurrent/repeated start() calls
        create AT MOST ONE thread. A no-op once stop() has begun or
        completed."""
        with self._lock:
            if self._state is not _WorkerLifecycleState.NOT_STARTED:
                return  # already RUNNING, STOPPING, or STOPPED -- never a second thread, never resurrected
            self._state = _WorkerLifecycleState.RUNNING
            thread = threading.Thread(
                target=self._lifecycle.run_forever, args=(self._runner_secret, self._stop_event),
                name="mcma-runner-job-worker", daemon=False,
            )
            self._thread = thread
            try:
                thread.start()
            except Exception:
                # threading.Thread.start() itself failed -- no OS thread
                # was ever created. Restore a truthful terminal state
                # immediately rather than leaving RUNNING published with a
                # Thread object that never actually started (which would
                # make a later stop()'s join() raise).
                self._state = _WorkerLifecycleState.STOPPED
                self._thread = None
                raise

    def stop(self, timeout: float) -> bool:
        """Bounded and idempotent: sets the stop signal and performs at
        most one bounded join per call, safe to call repeatedly (including
        before start(), and concurrently with it) without ever raising."""
        with self._lock:
            if self._state is _WorkerLifecycleState.NOT_STARTED:
                self._state = _WorkerLifecycleState.STOPPED
                return True
            if self._state is _WorkerLifecycleState.STOPPED:
                return True
            self._state = _WorkerLifecycleState.STOPPING
            thread = self._thread
        self._stop_event.set()
        if thread is not None:
            thread.join(timeout=timeout)
        stopped = thread is None or not thread.is_alive()
        if stopped:
            with self._lock:
                self._state = _WorkerLifecycleState.STOPPED
        return stopped

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()
