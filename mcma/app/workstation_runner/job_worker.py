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
    # Phase 1C-C: EXECUTE's own lifecycle events -- kept distinct from
    # JOB_STARTED/JOB_SUCCEEDED/JOB_FAILED above (never reused) so a
    # listener (mcma.app.workstation_runner.controller) can show EXECUTE's
    # own fixed French status text without guessing a claimed job's mode
    # from context.
    EXECUTE_STARTED = "EXECUTE_STARTED"
    EXECUTE_SUCCEEDED = "EXECUTE_SUCCEEDED"
    EXECUTE_FAILED = "EXECUTE_FAILED"


class ClaimedJobLike(Protocol):
    job_id: str
    mode: str
    claim_token: str
    generation: int


class StartedJobLike(Protocol):
    status: str
    job_status: str
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

# Phase 1C-C: the async EXECUTE executor -- structurally
# mcma.app.workstation_runner.execute_executor.run_execute_check, called
# with the SAME (claimed_job, plan_hash) shape as RunDryRunCheck via a
# caller-supplied closure (expected_plan_hash, session_store,
# workflow_registry, perform_execute_write are all already bound by the
# composition root). Optional: a worker that is never handed one simply
# can never be handed an EXECUTE envelope either (claim_job's own server-
# side gate, EXECUTE_DISPATCH_ENABLED, is what actually prevents that in
# production -- this parameter's absence is not itself a safety boundary).
RunExecuteCheck = Callable[[ClaimedJobLike, str], Awaitable[str]]  # (claimed_job, plan_hash) -> EXECUTE_FINISH_RESULTS member

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
        run_execute_check: Optional[RunExecuteCheck] = None,
        is_ready: Callable[[], bool] = lambda: False,
        on_event: OnEvent = lambda event: None,
        wait: Callable[[threading.Event, float], bool] = _default_wait,
        poll_interval_seconds: float = _DEFAULT_POLL_INTERVAL_SECONDS,
        renew_interval_seconds: float = _DEFAULT_RENEW_INTERVAL_SECONDS,
        shutdown_poll_interval_seconds: float = _SHUTDOWN_POLL_INTERVAL_SECONDS,
    ) -> None:
        self._client = client
        self._run_dry_run_check = run_dry_run_check
        self._run_execute_check = run_execute_check
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

    def _safe_finish(self, runner_secret: str, claimed: ClaimedJobLike, result: str):
        """Best-effort finish() -- an expired/fenced assignment is the
        server's own truthful landing either way. Returns the parsed
        FinishResult on success, or None on ANY failure (transport,
        protocol, or fencing) -- callers that must never display success
        without server confirmation (Phase 1C-C correction, finding 2)
        check this return value, never just "did the call raise"."""
        try:
            return self._client.finish_job(
                runner_secret, job_id=claimed.job_id, claim_token=claimed.claim_token,
                generation=claimed.generation, result=result,
            )
        except Exception:
            return None

    def _run_one_job(self, runner_secret: str, claimed: ClaimedJobLike, stop_event: threading.Event) -> None:
        try:
            started = self._client.start_job(
                runner_secret, job_id=claimed.job_id, claim_token=claimed.claim_token, generation=claimed.generation,
            )
        except Exception:
            self._on_event(LifecycleEvent.CONNECTION_FAILED)
            return

        if claimed.mode == "EXECUTE":
            self._run_one_execute_job(runner_secret, claimed, started, stop_event)
            return

        # DRY_RUN -- correlate the start response against the EXACT shape
        # a claimed DRY_RUN job requires (Phase 1C-C correction, finding
        # 3): never a union of "any status/job_status this client happens
        # to accept", always the one pairing this job's own claimed mode
        # is legal for.
        if started.status == "NEEDS_REVIEW" and started.job_status == "NEEDS_REVIEW":
            # The server already resolved this job through planning alone
            # -- no browser work, nothing further for this worker to do.
            return
        if started.status != "RUNNING" or started.job_status != "READ_ONLY_IDENTITY_CHECK":
            # A cross-mode (e.g. EXECUTE's own IDENTITY_VERIFYING) or
            # otherwise inconsistent start response for a claimed DRY_RUN
            # job -- the DRY_RUN executor is never invoked. status==
            # "RUNNING" means the dispatch row is DEFINITELY running
            # server-side (certain either way, by the closed shape http_
            # client.py's start_job() already validated) -- never
            # released; a fixed, existing DRY_RUN result the server can
            # accept fails it closed instead. Any other, more ambiguous
            # response is abandoned locally, never guessed at, and left to
            # the server's own fenced lease-expiry recovery.
            if started.status == "RUNNING":
                self._safe_finish(runner_secret, claimed, "PORTAL_READ_FAILED")
            self._on_event(LifecycleEvent.JOB_FAILED)
            return

        self._on_event(LifecycleEvent.JOB_STARTED)
        result = asyncio.run(self._run_and_renew(runner_secret, claimed, started, stop_event))
        self._safe_finish(runner_secret, claimed, result)
        self._on_event(LifecycleEvent.JOB_SUCCEEDED if result == "IDENTITY_MATCHED" else LifecycleEvent.JOB_FAILED)

    def _run_one_execute_job(
        self, runner_secret: str, claimed: ClaimedJobLike, started, stop_event: threading.Event,
    ) -> None:
        """Phase 1C-C: the EXECUTE twin of the DRY_RUN branch above. Kept
        as a separate method (never folded into the DRY_RUN branch by an
        if/else sprinkled through it) so the two pipelines stay easy to
        read and to change independently -- they share only the started_
        job/start_job() admission that already happened in the caller."""
        # Correlate the start response against the EXACT shape a claimed
        # EXECUTE job requires (finding 3): NEEDS_REVIEW is legal ONLY for
        # DRY_RUN -- an EXECUTE job's own approved plan can never need
        # review (the server's own start_job() already fails that closed),
        # so an EXECUTE+NEEDS_REVIEW response is never trusted here either.
        if started.status != "RUNNING" or started.job_status != "IDENTITY_VERIFYING":
            if started.status == "RUNNING":
                # DEFINITELY running server-side (certain, by the closed
                # shape http_client.py already validated) -- never
                # released; a fixed, existing EXECUTE result the server
                # can accept fails it closed instead of invoking the write
                # executor on a job_status this worker cannot trust.
                self._safe_finish(runner_secret, claimed, "INTERNAL_EXECUTION_ERROR")
            # Anything else (an inconsistent NEEDS_REVIEW, or a status
            # this client cannot otherwise account for) is abandoned
            # locally -- never guessed -- and left to the server's own
            # fenced lease-expiry recovery.
            self._on_event(LifecycleEvent.EXECUTE_FAILED)
            return

        if self._run_execute_check is None:
            # Structurally unreachable in production (EXECUTE_DISPATCH_
            # ENABLED gates this server-side, long before a claim could
            # ever report mode="EXECUTE" to a worker with no executor
            # wired) -- but never silently drops the assignment: reported
            # as a fixed, fail-closed outcome like every other EXECUTE
            # failure, never an uncaught exception killing this thread.
            self._safe_finish(runner_secret, claimed, "INTERNAL_EXECUTION_ERROR")
            self._on_event(LifecycleEvent.EXECUTE_FAILED)
            return

        self._on_event(LifecycleEvent.EXECUTE_STARTED)
        result = asyncio.run(self._run_and_renew_execute(runner_secret, claimed, started, stop_event))
        finish_result = self._safe_finish(runner_secret, claimed, result)
        # Finding 2: EXECUTE_SUCCEEDED is NEVER emitted from the local
        # executor's own return value alone -- only when the SERVER's own
        # finish() response explicitly confirms BOTH the terminal dispatch
        # status and the terminal job status. A raised exception (rejected
        # finish, a transport/protocol failure, an already-expired claim)
        # or any other/partial/mismatched response is fail-closed to
        # EXECUTE_FAILED -- the final visible state is never success
        # unless the server said so.
        confirmed = (
            finish_result is not None
            and getattr(finish_result, "status", None) == "SUCCEEDED"
            and getattr(finish_result, "job_status", None) == "READY_FOR_HUMAN_REVIEW"
        )
        if finish_result is None:
            self._on_event(LifecycleEvent.CONNECTION_FAILED)
        self._on_event(LifecycleEvent.EXECUTE_SUCCEEDED if confirmed else LifecycleEvent.EXECUTE_FAILED)

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

    async def _run_and_renew_execute(
        self, runner_secret: str, claimed: ClaimedJobLike, started, stop_event: threading.Event,
    ) -> str:
        """Phase 1C-C, EXECUTE's own twin of _run_and_renew. Critical
        difference from DRY_RUN (see _renew_forever_execute's own
        docstring): a renewal failure here is NOT best-effort-swallowed --
        it sets `lease_lost`, and this loop cancels the write task the
        moment either `stop_event` or `lease_lost` fires. Once mutation may
        have begun, this worker never keeps writing on a lease it can no
        longer prove it still holds.

        Correction (Phase 1C-C, finding 4): the two cancellation causes are
        DISTINGUISHED, not collapsed into one generic outcome -- an
        operator-driven shutdown reports "RUNNER_CANCELLED", a lost lease
        reports "LEASE_LOST" (both members of EXECUTE_FINISH_RESULTS,
        mapped server-side to WRITE_ABORTED with their own distinct
        reason_code). Deterministic priority when both are already true at
        the SAME poll: `stop_event` wins -- checked first, every
        iteration -- because an operator-requested shutdown is a more
        specific, more intentional signal than an incidental renewal
        failure racing it. Either way, this never returns the job to
        PLANNED or leaves it automatically claimable again: a finish()
        call reporting either result, if it still reaches an assignment
        the server considers RUNNING, lands on WRITE_ABORTED; if the lease
        had ALREADY genuinely expired server-side by the time finish() is
        attempted, that call is simply refused (CLAIM_NOT_FOUND) -- the
        server's own expire_stale_assignments/fail_closed_on_runner_
        exception path (INTERRUPTED_NEEDS_HUMAN_REVIEW) remains the
        authoritative landing in that case, and this worker's own finish
        attempt failing is expected and harmless."""
        exec_task = asyncio.ensure_future(self._run_execute_check(claimed, started.plan_hash))
        lease_lost = asyncio.Event()
        renew_task = asyncio.ensure_future(self._renew_forever_execute(runner_secret, claimed, lease_lost))
        cancel_reason = "WRITE_ABORTED"  # fail-closed fallback; overwritten below whenever this module cancels
        try:
            while not exec_task.done():
                if stop_event.is_set():
                    cancel_reason = "RUNNER_CANCELLED"  # priority: shutdown wins over a lease lost at the same poll
                    exec_task.cancel()
                    break
                if lease_lost.is_set():
                    cancel_reason = "LEASE_LOST"
                    exec_task.cancel()
                    break
                await asyncio.sleep(self._shutdown_poll_interval_seconds)
            try:
                return await exec_task
            except asyncio.CancelledError:
                # Fail-closed, never a guess: this module has no visibility
                # into whether the injected write callable had already
                # begun mutating the portal when it was cancelled -- the
                # critical rule this increment requires (never
                # automatically retry, never PLANNED/claimable again)
                # holds regardless of which of the two causes fired.
                return cancel_reason
        finally:
            renew_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await renew_task

    async def _renew_forever_execute(
        self, runner_secret: str, claimed: ClaimedJobLike, lease_lost: asyncio.Event,
    ) -> None:
        """EXECUTE-only renewal loop. Unlike DRY_RUN's _renew_forever
        (where a lost lease is harmless -- finish_job's own server-side
        fencing is the truthful landing either way, no live write is ever
        at risk), an EXECUTE renewal failure means this worker can no
        longer PROVE it still owns the account it may be mid-write on: it
        sets `lease_lost` and returns immediately -- the caller cancels the
        write task the moment this fires, per this increment's own
        critical rule (stop mutation immediately when lease ownership is
        lost or renewal is refused)."""
        try:
            while True:
                await asyncio.sleep(self._renew_interval_seconds)
                try:
                    await asyncio.to_thread(
                        self._client.renew_job, runner_secret, job_id=claimed.job_id,
                        claim_token=claimed.claim_token, generation=claimed.generation,
                    )
                except Exception:
                    lease_lost.set()
                    return
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
