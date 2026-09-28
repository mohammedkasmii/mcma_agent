"""mcma.app.workstation_runner.job_worker -- Phase 1C-B, item D. Unit-level:
the RegistryHttpClient and the executor are both plain fakes/coroutines,
never real HTTP/Playwright. No real sleeps -- `wait` is injected for the
outer poll/backoff loop, and the inner shutdown-watch loop's
`asyncio.sleep(0)`-style yields (via a zero `shutdown_poll_interval_seconds`)
are pure cooperative yields, never a wall-clock delay."""

import asyncio
import threading
import time
from dataclasses import dataclass
from typing import Optional

from mcma.app.workstation_runner.job_worker import (
    _INITIAL_BACKOFF_SECONDS, JobPollingLifecycle, JobPollingWorker, LifecycleEvent,
)


@dataclass(frozen=True)
class FakeClaimedJob:
    job_id: str = "job-1"
    mode: str = "DRY_RUN"
    claim_token: str = "mcma_ct_" + "t" * 40
    generation: int = 1
    account_id: str = "acct-mcma-oujda"


@dataclass(frozen=True)
class FakeStartedJob:
    status: str
    # Defaults to the DRY_RUN shape -- the common case in this file's
    # pre-existing tests, most of which construct only `status`/
    # `plan_hash`. Every EXECUTE-mode test below sets this explicitly.
    job_status: str = "READ_ONLY_IDENTITY_CHECK"
    plan_hash: Optional[str] = None


@dataclass(frozen=True)
class FakeFinishResult:
    status: str
    job_status: str
    server_time: str = "t"


class FakeClient:
    def __init__(self):
        self.claim_queue: list = []
        self.claim_calls = 0
        self.start_calls: list = []
        self.start_result = FakeStartedJob(status="RUNNING", plan_hash="h" * 64)
        self.renew_calls: list = []
        self.release_calls: list = []
        self.finish_calls: list = []
        self.browser_closed_calls: list = []
        # Phase 1C-C Pass 2A: None (the default) means "always succeeds
        # immediately" -- a test overrides this with a callable/exception
        # to exercise _report_browser_closed_with_retry's own retry path.
        self.browser_closed_raises = None
        # The SERVER-confirmed shape finish_job() returns. None (the
        # default) auto-derives a realistic response FROM the `result`
        # argument actually passed (mirroring dispatch.py's own mapping
        # tables closely enough for these tests' purposes); a test
        # overrides this to exercise finding 2's "never display success
        # without server confirmation" rule with a rejected/mismatched/
        # exception-raising finish.
        self.finish_result = None
        self.closed = False
        self.call_order: list = []

    def claim_job(self, runner_secret):
        self.claim_calls += 1
        self.call_order.append("claim")
        if not self.claim_queue:
            return None
        item = self.claim_queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def start_job(self, runner_secret, *, job_id, claim_token, generation):
        self.start_calls.append((job_id, claim_token, generation))
        self.call_order.append("start")
        if isinstance(self.start_result, Exception):
            raise self.start_result
        return self.start_result

    def renew_job(self, runner_secret, *, job_id, claim_token, generation):
        self.renew_calls.append((job_id, claim_token, generation))
        self.call_order.append("renew")

    def release_job(self, runner_secret, *, job_id, claim_token, generation, reason_code):
        self.release_calls.append((job_id, claim_token, generation, reason_code))
        self.call_order.append("release")

    def finish_job(self, runner_secret, *, job_id, claim_token, generation, result):
        self.finish_calls.append((job_id, claim_token, generation, result))
        self.call_order.append("finish")
        if isinstance(self.finish_result, Exception):
            raise self.finish_result
        if self.finish_result is not None:
            return self.finish_result
        if result == "IDENTITY_MATCHED":
            return FakeFinishResult(status="SUCCEEDED", job_status="DRY_RUN_VERIFIED")
        if result == "READY_FOR_HUMAN_REVIEW":
            return FakeFinishResult(status="SUCCEEDED", job_status="READY_FOR_HUMAN_REVIEW")
        return FakeFinishResult(status="FAILED", job_status=result)

    def report_execute_review_browser_closed(self, runner_secret, *, job_id, claim_token, generation):
        self.browser_closed_calls.append((job_id, claim_token, generation))
        self.call_order.append("browser_closed")
        if self.browser_closed_raises is not None:
            raise self.browser_closed_raises

    def close(self):
        self.closed = True


def _stop_after(n: int):
    """A `wait` function that stops run_forever's loop after N calls --
    never a real sleep (the underlying threading.Event.wait is never
    invoked at all)."""
    state = {"count": 0}

    def wait(event: threading.Event, timeout: float) -> bool:
        state["count"] += 1
        if state["count"] >= n:
            event.set()
        return event.is_set()

    return wait


async def _matches(claimed_job, plan_hash):
    return "IDENTITY_MATCHED"


async def _never_called(claimed_job, plan_hash):
    raise AssertionError("run_dry_run_check must never be called")


def test_no_claim_while_not_ready():
    client = FakeClient()
    lifecycle = JobPollingLifecycle(client, _never_called, is_ready=lambda: False, wait=lambda e, t: True)
    lifecycle.run_forever("secret", threading.Event())
    assert client.claim_calls == 0


def test_no_claim_while_stop_event_already_set():
    client = FakeClient()
    stop_event = threading.Event()
    stop_event.set()
    lifecycle = JobPollingLifecycle(client, _never_called, is_ready=lambda: True)
    lifecycle.run_forever("secret", stop_event)
    assert client.claim_calls == 0


def test_polls_again_when_nothing_is_eligible():
    client = FakeClient()  # claim_queue empty -> claim_job returns None every time
    lifecycle = JobPollingLifecycle(client, _never_called, is_ready=lambda: True, wait=_stop_after(3))
    lifecycle.run_forever("secret", threading.Event())
    assert client.claim_calls == 3


def test_start_happens_before_the_executor_is_invoked():
    client = FakeClient()
    client.claim_queue = [FakeClaimedJob()]
    order = []

    async def _check(claimed_job, plan_hash):
        order.append("executor")
        return "IDENTITY_MATCHED"

    lifecycle = JobPollingLifecycle(client, _check, is_ready=lambda: True, wait=_stop_after(1))
    lifecycle.run_forever("secret", threading.Event())
    # A second "claim" (finding no further work, then stopping via wait())
    # legitimately follows the first job's own claim/start/finish sequence
    # -- wait() is only ever called on an IDLE iteration.
    assert client.call_order[:3] == ["claim", "start", "finish"]
    assert order == ["executor"]


def test_needs_review_start_response_never_invokes_the_executor():
    client = FakeClient()
    client.claim_queue = [FakeClaimedJob()]
    client.start_result = FakeStartedJob(status="NEEDS_REVIEW", job_status="NEEDS_REVIEW", plan_hash=None)
    lifecycle = JobPollingLifecycle(client, _never_called, is_ready=lambda: True, wait=_stop_after(1))
    lifecycle.run_forever("secret", threading.Event())
    assert client.call_order[:2] == ["claim", "start"]
    assert client.finish_calls == []


def test_shutdown_between_claim_and_start_releases_not_starts():
    client = FakeClient()
    stop_event = threading.Event()
    claimed = FakeClaimedJob()

    def claim_then_shutdown(secret):
        stop_event.set()
        return claimed

    client.claim_job = claim_then_shutdown
    lifecycle = JobPollingLifecycle(client, _never_called, is_ready=lambda: True)
    lifecycle.run_forever("secret", stop_event)
    assert client.release_calls == [(claimed.job_id, claimed.claim_token, claimed.generation, "RUNNER_SHUTDOWN")]
    assert client.start_calls == []


def test_shutdown_while_running_cancels_the_executor_and_reports_runner_cancelled():
    async def _hangs_forever(claimed_job, plan_hash):
        await asyncio.Event().wait()  # never completes on its own

    client = FakeClient()
    claimed = FakeClaimedJob()
    started = FakeStartedJob(status="RUNNING", plan_hash="h" * 64)
    stop_event = threading.Event()
    stop_event.set()  # shutdown already requested before this job's pipeline is entered
    lifecycle = JobPollingLifecycle(client, _hangs_forever, is_ready=lambda: True, shutdown_poll_interval_seconds=0)
    result = asyncio.run(lifecycle._run_and_renew("secret", claimed, started, stop_event))
    assert result == "RUNNER_CANCELLED"
    assert client.release_calls == []  # never release() once RUNNING


def test_once_running_release_is_never_called_only_finish():
    client = FakeClient()
    client.claim_queue = [FakeClaimedJob()]
    lifecycle = JobPollingLifecycle(client, _matches, is_ready=lambda: True, wait=_stop_after(1))
    lifecycle.run_forever("secret", threading.Event())
    assert client.release_calls == []
    assert len(client.finish_calls) == 1
    assert client.finish_calls[0][3] == "IDENTITY_MATCHED"


def test_no_new_work_starts_after_shutdown_even_with_eligible_jobs_queued():
    client = FakeClient()
    client.claim_queue = [FakeClaimedJob(job_id="job-1"), FakeClaimedJob(job_id="job-2")]
    stop_event = threading.Event()
    stop_event.set()
    lifecycle = JobPollingLifecycle(client, _never_called, is_ready=lambda: True)
    lifecycle.run_forever("secret", stop_event)
    assert client.claim_calls == 0
    assert client.start_calls == []


def test_lease_renews_while_the_executor_is_blocked():
    client = FakeClient()
    claimed = FakeClaimedJob()
    started = FakeStartedJob(status="RUNNING", plan_hash="h" * 64)
    renew_count_when_executor_finishes = []

    async def _slow_check(claimed_job, plan_hash):
        # Cooperative yields only (asyncio.sleep(0) never waits real time)
        # -- gives the renewal task (interval=0) several chances to run
        # before this returns.
        for _ in range(20):
            await asyncio.sleep(0)
        renew_count_when_executor_finishes.append(len(client.renew_calls))
        return "IDENTITY_MATCHED"

    lifecycle = JobPollingLifecycle(client, _slow_check, is_ready=lambda: True, renew_interval_seconds=0)
    result = asyncio.run(lifecycle._run_and_renew("secret", claimed, started, threading.Event()))
    assert result == "IDENTITY_MATCHED"
    assert renew_count_when_executor_finishes[0] > 0


def test_renewal_stops_once_the_executor_finishes():
    client = FakeClient()
    claimed = FakeClaimedJob()
    started = FakeStartedJob(status="RUNNING", plan_hash="h" * 64)

    async def _quick_check(claimed_job, plan_hash):
        return "IDENTITY_MATCHED"

    lifecycle = JobPollingLifecycle(client, _quick_check, is_ready=lambda: True, renew_interval_seconds=0)
    asyncio.run(lifecycle._run_and_renew("secret", claimed, started, threading.Event()))
    count_at_return = len(client.renew_calls)
    # A moment later (a fresh event loop tick, no real wait), the count
    # must not have kept climbing -- the renewal task was cancelled.
    asyncio.run(asyncio.sleep(0))
    assert len(client.renew_calls) == count_at_return


def test_malformed_claim_response_fails_closed_with_backoff_not_a_crash():
    client = FakeClient()
    client.claim_queue = [RuntimeError("malformed envelope")]
    events = []
    lifecycle = JobPollingLifecycle(
        client, _never_called, is_ready=lambda: True, on_event=events.append, wait=_stop_after(1),
    )
    lifecycle.run_forever("secret", threading.Event())  # must not raise
    assert LifecycleEvent.CONNECTION_FAILED in events


def test_malformed_start_response_fails_closed_with_backoff_not_a_crash():
    client = FakeClient()
    client.claim_queue = [FakeClaimedJob()]
    client.start_result = RuntimeError("malformed envelope")
    events = []
    lifecycle = JobPollingLifecycle(
        client, _never_called, is_ready=lambda: True, on_event=events.append, wait=_stop_after(1),
    )
    lifecycle.run_forever("secret", threading.Event())  # must not raise
    assert LifecycleEvent.CONNECTION_FAILED in events
    assert client.finish_calls == []


def test_on_event_carries_only_fixed_enum_members_never_data():
    client = FakeClient()
    client.claim_queue = [FakeClaimedJob()]
    events = []
    lifecycle = JobPollingLifecycle(
        client, _matches, is_ready=lambda: True, on_event=events.append, wait=_stop_after(1),
    )
    lifecycle.run_forever("secret", threading.Event())
    assert events
    assert all(isinstance(e, LifecycleEvent) for e in events)


def test_secret_and_claim_token_never_appear_in_any_event_or_call_argument_repr():
    """The worker never logs; this proves there is nothing TO leak even if
    it did -- every value passed to on_event is a bare enum member."""
    client = FakeClient()
    claimed = FakeClaimedJob(claim_token="mcma_ct_" + "SENSITIVE" * 4)
    client.claim_queue = [claimed]
    events = []
    lifecycle = JobPollingLifecycle(
        client, _matches, is_ready=lambda: True, on_event=events.append, wait=_stop_after(1),
    )
    lifecycle.run_forever("secret-value", threading.Event())
    for event in events:
        assert "SENSITIVE" not in repr(event)
        assert "secret-value" not in repr(event)


def test_the_client_is_always_closed_when_run_forever_returns():
    client = FakeClient()
    lifecycle = JobPollingLifecycle(client, _never_called, is_ready=lambda: False, wait=lambda e, t: True)
    lifecycle.run_forever("secret", threading.Event())
    assert client.closed is True


def test_worker_thread_wrapper_start_stop_is_idempotent_and_bounded():
    client = FakeClient()
    lifecycle = JobPollingLifecycle(client, _never_called, is_ready=lambda: False)
    worker = JobPollingWorker(lifecycle, "secret")
    worker.start()
    try:
        assert worker.is_alive()
    finally:
        assert worker.stop(timeout=5.0) is True
        assert worker.stop(timeout=5.0) is True  # idempotent -- safe to call again
    assert not worker.is_alive()


class _CountingLifecycle:
    """Records every run_forever() invocation and the OS thread identity
    it ran on -- proves AT MOST ONE call, on AT MOST ONE thread, no matter
    how many times start() is (or appears to be) called."""

    def __init__(self):
        self.run_calls: list = []
        self.thread_idents: set = set()
        self._entered = threading.Event()

    def run_forever(self, secret, stop_event):
        import threading as _threading

        self.run_calls.append(secret)
        self.thread_idents.add(_threading.get_ident())
        self._entered.set()
        stop_event.wait()

    def wait_until_entered(self, timeout=2.0) -> bool:
        return self._entered.wait(timeout)


def test_calling_start_twice_creates_at_most_one_thread():
    lifecycle = _CountingLifecycle()
    worker = JobPollingWorker(lifecycle, "secret")
    worker.start()
    worker.start()  # the exact scenario the old test never actually exercised
    try:
        assert lifecycle.wait_until_entered()
    finally:
        assert worker.stop(timeout=5.0) is True
    assert lifecycle.run_calls == ["secret"]
    assert len(lifecycle.thread_idents) == 1


def test_calling_start_concurrently_from_several_threads_creates_at_most_one_thread():
    lifecycle = _CountingLifecycle()
    worker = JobPollingWorker(lifecycle, "secret")
    starters = [threading.Thread(target=worker.start) for _ in range(8)]
    for t in starters:
        t.start()
    for t in starters:
        t.join(timeout=5.0)
    try:
        assert lifecycle.wait_until_entered()
    finally:
        assert worker.stop(timeout=5.0) is True
    assert lifecycle.run_calls == ["secret"]
    assert len(lifecycle.thread_idents) == 1


def test_racing_start_against_stop_never_resurrects_a_stopped_worker():
    """Whichever of start()/stop() reaches the lock first is authoritative
    -- if stop() wins, the worker must stay stopped forever, never
    resurrected by a start() that was already in flight."""
    for _ in range(20):  # repeat: this is a genuine race, not deterministic ordering
        lifecycle = _CountingLifecycle()
        worker = JobPollingWorker(lifecycle, "secret")
        starter = threading.Thread(target=worker.start)
        stopper = threading.Thread(target=lambda: worker.stop(timeout=5.0))
        starter.start()
        stopper.start()
        starter.join(timeout=5.0)
        stopper.join(timeout=5.0)
        assert worker.stop(timeout=5.0) is True  # always converges to stopped, never raises
        assert not worker.is_alive()
        # Regardless of which one won the race, a start() AFTER this point
        # must never resurrect the worker.
        worker.start()
        assert not worker.is_alive()
        assert len(lifecycle.thread_idents) <= 1


def test_stop_before_start_leaves_the_worker_permanently_stopped():
    lifecycle = _CountingLifecycle()
    worker = JobPollingWorker(lifecycle, "secret")
    assert worker.stop(timeout=1.0) is True
    worker.start()
    assert not worker.is_alive()
    assert lifecycle.run_calls == []


def test_stop_is_idempotent_and_never_raises_when_called_many_times():
    lifecycle = _CountingLifecycle()
    worker = JobPollingWorker(lifecycle, "secret")
    worker.start()
    assert lifecycle.wait_until_entered()
    for _ in range(5):
        assert worker.stop(timeout=2.0) is True
    assert not worker.is_alive()


# --------------------------------------------------------------------- #
# Phase 1C-C -- EXECUTE envelopes, run_execute_check, and the lease-loss-
# cancels-mutation critical rule (item 5).
# --------------------------------------------------------------------- #


async def _execute_ready_for_review(claimed_job, plan_hash, permit, on_ready_for_review, on_phase):
    """Phase 1C-C Pass 2A: mirrors what the real write callable does --
    calls on_phase for each automation phase, then on_ready_for_review
    BEFORE returning READY_FOR_HUMAN_REVIEW (mcma.portal.
    workstation_execute.run_workstation_execute_write's own contract:
    finish is reported, and the browser is "closed", before this
    coroutine returns)."""
    on_phase("WRITING")
    on_phase("VERIFYING")
    await on_ready_for_review()
    return "READY_FOR_HUMAN_REVIEW"


async def _execute_never_called(claimed_job, plan_hash, permit, on_ready_for_review, on_phase):
    raise AssertionError("run_execute_check must never be called")


def _execute_claimed(**overrides):
    return FakeClaimedJob(mode="EXECUTE", **overrides)


def _execute_started(**overrides):
    return FakeStartedJob(status="RUNNING", job_status="IDENTITY_VERIFYING", plan_hash="h" * 64, **overrides)


def test_execute_job_runs_through_start_executor_review_confirmation_and_browser_closed_report():
    client = FakeClient()
    client.claim_queue = [_execute_claimed()]
    client.start_result = _execute_started()
    order = []

    async def _check(claimed_job, plan_hash, permit, on_ready_for_review, on_phase):
        order.append("executor")
        await on_ready_for_review()
        return "READY_FOR_HUMAN_REVIEW"

    lifecycle = JobPollingLifecycle(
        client, _never_called, run_execute_check=_check, is_ready=lambda: True, wait=_stop_after(1),
    )
    lifecycle.run_forever("secret", threading.Event())
    # Requirements 7/10: finish() is reported BEFORE the (already-closed,
    # in this fake) browser wait returns, and the browser-closed event is
    # reported AFTER -- never a finish_job call after browser_closed.
    assert client.call_order[:4] == ["claim", "start", "finish", "browser_closed"]
    assert order == ["executor"]
    assert client.finish_calls[0][3] == "READY_FOR_HUMAN_REVIEW"
    assert len(client.browser_closed_calls) == 1


def test_execute_needs_review_start_response_never_invokes_the_executor():
    """Finding 3: NEEDS_REVIEW is legal ONLY for DRY_RUN -- an EXECUTE
    claim reporting it is never trusted, the write executor is never
    invoked, and (status != RUNNING, so the dispatch row's true state is
    ambiguous from here) no finish() attempt is made either -- left to the
    server's own fenced lease-expiry recovery."""
    client = FakeClient()
    client.claim_queue = [_execute_claimed()]
    client.start_result = FakeStartedJob(status="NEEDS_REVIEW", job_status="NEEDS_REVIEW", plan_hash=None)
    events = []
    lifecycle = JobPollingLifecycle(
        client, _never_called, run_execute_check=_execute_never_called, is_ready=lambda: True,
        on_event=events.append, wait=_stop_after(1),
    )
    lifecycle.run_forever("secret", threading.Event())
    assert client.call_order[:2] == ["claim", "start"]
    assert client.finish_calls == []
    assert LifecycleEvent.EXECUTE_FAILED in events
    assert LifecycleEvent.EXECUTE_SUCCEEDED not in events


def test_execute_read_only_identity_check_start_response_never_invokes_the_write_executor():
    """Finding 3: a claimed EXECUTE job whose start response carries
    DRY_RUN's own job_status (cross-mode/inconsistent) never invokes the
    write executor -- status=="RUNNING" here means the dispatch row IS
    running server-side, so this is fenced closed with an existing,
    EXECUTE-legal result the server can accept, never released."""
    client = FakeClient()
    client.claim_queue = [_execute_claimed()]
    client.start_result = FakeStartedJob(status="RUNNING", job_status="READ_ONLY_IDENTITY_CHECK", plan_hash="h" * 64)
    events = []
    lifecycle = JobPollingLifecycle(
        client, _never_called, run_execute_check=_execute_never_called, is_ready=lambda: True,
        on_event=events.append, wait=_stop_after(1),
    )
    lifecycle.run_forever("secret", threading.Event())
    assert client.finish_calls[0][3] == "INTERNAL_EXECUTION_ERROR"
    assert client.release_calls == []  # never release() once RUNNING
    assert LifecycleEvent.EXECUTE_FAILED in events
    assert LifecycleEvent.EXECUTE_SUCCEEDED not in events


def test_dry_run_identity_verifying_start_response_never_invokes_the_read_executor():
    """Finding 3, the reverse pairing: a claimed DRY_RUN job whose start
    response carries EXECUTE's own job_status never invokes the DRY_RUN
    (read-only) executor -- fenced closed with an existing, DRY_RUN-legal
    result, never released."""
    client = FakeClient()
    client.claim_queue = [FakeClaimedJob()]  # mode="DRY_RUN" (default)
    client.start_result = FakeStartedJob(status="RUNNING", job_status="IDENTITY_VERIFYING", plan_hash="h" * 64)
    events = []
    lifecycle = JobPollingLifecycle(
        client, _never_called, is_ready=lambda: True, on_event=events.append, wait=_stop_after(1),
    )
    lifecycle.run_forever("secret", threading.Event())
    assert client.finish_calls[0][3] == "PORTAL_READ_FAILED"
    assert client.release_calls == []  # never release() once RUNNING
    assert LifecycleEvent.JOB_FAILED in events
    assert LifecycleEvent.JOB_SUCCEEDED not in events


def test_valid_dry_run_and_execute_pairings_still_invoke_their_own_executor():
    """Positive control for finding 3: with no interference, both valid
    pairings still work exactly as before this correction."""
    dry_run_client = FakeClient()
    dry_run_client.claim_queue = [FakeClaimedJob()]
    dry_run_lifecycle = JobPollingLifecycle(dry_run_client, _matches, is_ready=lambda: True, wait=_stop_after(1))
    dry_run_lifecycle.run_forever("secret", threading.Event())
    assert dry_run_client.finish_calls[0][3] == "IDENTITY_MATCHED"

    execute_client = FakeClient()
    execute_client.claim_queue = [_execute_claimed()]
    execute_client.start_result = _execute_started()
    execute_lifecycle = JobPollingLifecycle(
        execute_client, _never_called, run_execute_check=_execute_ready_for_review,
        is_ready=lambda: True, wait=_stop_after(1),
    )
    execute_lifecycle.run_forever("secret", threading.Event())
    assert execute_client.finish_calls[0][3] == "READY_FOR_HUMAN_REVIEW"


def test_execute_events_are_distinct_from_dry_run_events():
    client = FakeClient()
    client.claim_queue = [_execute_claimed()]
    client.start_result = _execute_started()
    events = []
    lifecycle = JobPollingLifecycle(
        client, _never_called, run_execute_check=_execute_ready_for_review, is_ready=lambda: True,
        on_event=events.append, wait=_stop_after(1),
    )
    lifecycle.run_forever("secret", threading.Event())
    assert LifecycleEvent.EXECUTE_STARTED in events
    assert LifecycleEvent.EXECUTE_SUCCEEDED in events
    assert LifecycleEvent.JOB_STARTED not in events
    assert LifecycleEvent.JOB_SUCCEEDED not in events


def test_execute_failure_outcome_emits_execute_failed():
    client = FakeClient()
    client.claim_queue = [_execute_claimed()]
    client.start_result = _execute_started()
    events = []

    async def _write_aborted(claimed_job, plan_hash, permit, on_ready_for_review, on_phase):
        return "WRITE_ABORTED"

    lifecycle = JobPollingLifecycle(
        client, _never_called, run_execute_check=_write_aborted, is_ready=lambda: True,
        on_event=events.append, wait=_stop_after(1),
    )
    lifecycle.run_forever("secret", threading.Event())
    assert LifecycleEvent.EXECUTE_FAILED in events
    assert client.finish_calls[0][3] == "WRITE_ABORTED"


def test_execute_claimed_with_no_executor_wired_fails_closed_never_starts_a_write():
    """Structurally unreachable in production (EXECUTE_DISPATCH_ENABLED
    gates this server-side) -- but if it ever happened, this worker must
    never crash and must never silently drop the assignment."""
    client = FakeClient()
    client.claim_queue = [_execute_claimed()]
    client.start_result = _execute_started()
    events = []
    lifecycle = JobPollingLifecycle(
        client, _never_called, run_execute_check=None, is_ready=lambda: True,
        on_event=events.append, wait=_stop_after(1),
    )
    lifecycle.run_forever("secret", threading.Event())  # must not raise
    assert LifecycleEvent.EXECUTE_FAILED in events
    assert client.finish_calls[0][3] == "INTERNAL_EXECUTION_ERROR"


# ---- finding 2: never display EXECUTE success without server confirmation ---- #
# Phase 1C-C Pass 2A handoff fix: on_ready_for_review now RETRIES an
# unconfirmed finish with real bounded backoff, forever, until confirmed
# OR this lifecycle is cancelled (stop_event/lease_lost) -- so a test
# whose finish() never confirms must ITSELF trigger stop_event (as a side
# effect of a finish attempt) to end the retry loop promptly, exactly as
# a real shutdown would. `_stop_after_finish_attempt` wraps the client's
# own finish_job and is reused by every "never confirms" test below.


def _stop_after_finish_attempt(client: FakeClient, stop_event: threading.Event) -> None:
    original_finish_job = client.finish_job

    def _finish_then_stop(*args, **kwargs):
        try:
            return original_finish_job(*args, **kwargs)
        finally:
            stop_event.set()

    client.finish_job = _finish_then_stop


def test_execute_success_is_shown_only_when_finish_explicitly_confirms_it():
    client = FakeClient()
    client.claim_queue = [_execute_claimed()]
    client.start_result = _execute_started()
    client.finish_result = FakeFinishResult(status="SUCCEEDED", job_status="READY_FOR_HUMAN_REVIEW")
    events = []
    lifecycle = JobPollingLifecycle(
        client, _never_called, run_execute_check=_execute_ready_for_review, is_ready=lambda: True,
        on_event=events.append, wait=_stop_after(1),
    )
    lifecycle.run_forever("secret", threading.Event())
    assert LifecycleEvent.EXECUTE_SUCCEEDED in events
    assert len(client.browser_closed_calls) == 1  # only a CONFIRMED finish ever reports browser-closed


def test_execute_rejected_finish_never_shows_success():
    """The local executor reported READY_FOR_HUMAN_REVIEW, but finish()
    itself raises (a rejected/expired claim, or any transport/protocol
    failure) on every attempt -- shutdown (triggered here as a side
    effect of the first attempt, standing in for an operator/lease-loss
    cancellation) ends the retry loop before it ever confirms; the final
    visible state must never be success, and browser-closed must never be
    reported against an unconfirmed assignment (requirement 3)."""
    client = FakeClient()
    client.claim_queue = [_execute_claimed()]
    client.start_result = _execute_started()
    client.finish_result = RuntimeError("CLAIM_NOT_FOUND")
    events = []
    stop_event = threading.Event()
    _stop_after_finish_attempt(client, stop_event)
    lifecycle = JobPollingLifecycle(
        client, _never_called, run_execute_check=_execute_ready_for_review, is_ready=lambda: True,
        on_event=events.append, wait=_stop_after(1), shutdown_poll_interval_seconds=0,
    )
    lifecycle.run_forever("secret", stop_event)
    assert LifecycleEvent.EXECUTE_SUCCEEDED not in events
    assert LifecycleEvent.EXECUTE_FAILED in events
    assert LifecycleEvent.CONNECTION_FAILED in events
    assert LifecycleEvent.EXECUTE_READY_FOR_REVIEW not in events
    assert LifecycleEvent.EXECUTE_REVIEW_IN_PROGRESS not in events
    assert client.browser_closed_calls == []


def test_execute_connection_failure_on_finish_never_shows_success():
    client = FakeClient()
    client.claim_queue = [_execute_claimed()]
    client.start_result = _execute_started()
    client.finish_result = ConnectionError("unreachable")
    events = []
    stop_event = threading.Event()
    _stop_after_finish_attempt(client, stop_event)
    lifecycle = JobPollingLifecycle(
        client, _never_called, run_execute_check=_execute_ready_for_review, is_ready=lambda: True,
        on_event=events.append, wait=_stop_after(1), shutdown_poll_interval_seconds=0,
    )
    lifecycle.run_forever("secret", stop_event)
    assert LifecycleEvent.EXECUTE_SUCCEEDED not in events
    assert LifecycleEvent.EXECUTE_FAILED in events
    assert LifecycleEvent.CONNECTION_FAILED in events
    assert client.browser_closed_calls == []


def test_execute_expired_claim_on_finish_never_shows_success():
    """A finish() call that arrives after the assignment's lease has
    already genuinely expired server-side is rejected -- same as any
    other finish() failure, never shown as success."""
    class FakeExpiredClaim(Exception):
        pass

    client = FakeClient()
    client.claim_queue = [_execute_claimed()]
    client.start_result = _execute_started()
    client.finish_result = FakeExpiredClaim("CLAIM_NOT_FOUND")
    events = []
    stop_event = threading.Event()
    _stop_after_finish_attempt(client, stop_event)
    lifecycle = JobPollingLifecycle(
        client, _never_called, run_execute_check=_execute_ready_for_review, is_ready=lambda: True,
        on_event=events.append, wait=_stop_after(1), shutdown_poll_interval_seconds=0,
    )
    lifecycle.run_forever("secret", stop_event)
    assert LifecycleEvent.EXECUTE_SUCCEEDED not in events
    assert LifecycleEvent.EXECUTE_FAILED in events
    assert client.browser_closed_calls == []


def test_execute_mismatched_finish_response_never_shows_success():
    """finish() itself succeeds (no exception) but its response does NOT
    confirm BOTH the terminal dispatch status AND the terminal job status
    -- never trusted as success, and retried exactly like a transport
    failure until shutdown ends the attempt."""
    client = FakeClient()
    client.claim_queue = [_execute_claimed()]
    client.start_result = _execute_started()
    client.finish_result = FakeFinishResult(status="FAILED", job_status="WRITE_ABORTED")
    events = []
    stop_event = threading.Event()
    _stop_after_finish_attempt(client, stop_event)
    lifecycle = JobPollingLifecycle(
        client, _never_called, run_execute_check=_execute_ready_for_review, is_ready=lambda: True,
        on_event=events.append, wait=_stop_after(1), shutdown_poll_interval_seconds=0,
    )
    lifecycle.run_forever("secret", stop_event)
    assert LifecycleEvent.EXECUTE_SUCCEEDED not in events
    assert LifecycleEvent.EXECUTE_FAILED in events
    assert client.browser_closed_calls == []


def test_execute_partially_confirmed_finish_response_never_shows_success():
    """dispatch status says SUCCEEDED but job_status disagrees -- still
    never trusted; BOTH fields must explicitly confirm success."""
    client = FakeClient()
    client.claim_queue = [_execute_claimed()]
    client.start_result = _execute_started()
    client.finish_result = FakeFinishResult(status="SUCCEEDED", job_status="IDENTITY_FAILED")
    events = []
    stop_event = threading.Event()
    _stop_after_finish_attempt(client, stop_event)
    lifecycle = JobPollingLifecycle(
        client, _never_called, run_execute_check=_execute_ready_for_review, is_ready=lambda: True,
        on_event=events.append, wait=_stop_after(1), shutdown_poll_interval_seconds=0,
    )
    lifecycle.run_forever("secret", stop_event)
    assert LifecycleEvent.EXECUTE_SUCCEEDED not in events
    assert LifecycleEvent.EXECUTE_FAILED in events
    assert client.browser_closed_calls == []


def test_finish_fails_twice_then_succeeds_renewal_stays_active_and_review_events_wait_for_confirmation():
    """Handoff-fix regression test: finish is retried across TWO failures
    before a third, successful, confirming attempt -- renewal must remain
    active throughout both failures (never stopped early), the SAME
    idempotent READY_FOR_HUMAN_REVIEW result is what eventually confirms,
    and EXECUTE_READY_FOR_REVIEW/EXECUTE_REVIEW_IN_PROGRESS fire only
    after that confirmation -- never during the two failures."""
    client = FakeClient()
    claimed = _execute_claimed()
    started = _execute_started()
    attempts: list = []

    def _fails_twice_then_confirms(runner_secret, *, job_id, claim_token, generation, result):
        attempts.append(result)
        if len(attempts) < 3:
            raise ConnectionError("transient")
        assert result == "READY_FOR_HUMAN_REVIEW"  # the SAME idempotent result every time
        return FakeFinishResult(status="SUCCEEDED", job_status="READY_FOR_HUMAN_REVIEW")

    client.finish_job = _fails_twice_then_confirms
    events = []
    lifecycle = JobPollingLifecycle(
        client, _never_called, run_execute_check=_execute_ready_for_review, is_ready=lambda: True,
        on_event=events.append, renew_interval_seconds=0,
    )
    # Patch asyncio.sleep for the backoff waits only, so this test does not
    # spend real wall-clock seconds on the (real, intentional) exponential
    # backoff between finish attempts -- everything else about the retry
    # loop, including renewal, runs for real.
    import unittest.mock

    real_sleep = asyncio.sleep

    async def _fast_sleep(delay, *a, **kw):
        if delay >= _INITIAL_BACKOFF_SECONDS:
            return await real_sleep(0, *a, **kw)
        return await real_sleep(delay, *a, **kw)

    with unittest.mock.patch("asyncio.sleep", _fast_sleep):
        outcome = asyncio.run(lifecycle._run_execute_lifecycle("secret", claimed, started, threading.Event()))
    assert attempts == ["READY_FOR_HUMAN_REVIEW"] * 3
    assert outcome.finish_attempted is True
    assert outcome.finish_confirmed is True
    assert len(client.renew_calls) > 0  # renewal genuinely kept running across both failures
    ready_index = events.index(LifecycleEvent.EXECUTE_READY_FOR_REVIEW)
    review_index = events.index(LifecycleEvent.EXECUTE_REVIEW_IN_PROGRESS)
    connection_failed_count = sum(1 for e in events if e is LifecycleEvent.CONNECTION_FAILED)
    assert connection_failed_count == 2  # exactly the two failed attempts, never after confirmation
    assert review_index > ready_index


def test_lost_response_after_server_commit_is_recovered_by_the_idempotent_retry():
    """Handoff-fix regression test: the FIRST finish request commits
    server-side, but its response is lost in transit (modelled here as
    the client raising on the first call despite having "committed") --
    the retry sends the SAME idempotent result again and the second
    (successful) response confirms it -- exactly one logical transition,
    and browser-close is subsequently accepted."""
    client = FakeClient()
    client.claim_queue = [_execute_claimed()]
    client.start_result = _execute_started()
    committed = {"value": False}

    def _commits_then_loses_response(runner_secret, *, job_id, claim_token, generation, result):
        if not committed["value"]:
            committed["value"] = True
            raise ConnectionError("response lost after server commit")
        return FakeFinishResult(status="SUCCEEDED", job_status="READY_FOR_HUMAN_REVIEW")

    client.finish_job = _commits_then_loses_response
    events = []
    lifecycle = JobPollingLifecycle(
        client, _never_called, run_execute_check=_execute_ready_for_review, is_ready=lambda: True,
        on_event=events.append, wait=_stop_after(1),
    )
    lifecycle.run_forever("secret", threading.Event())
    assert LifecycleEvent.EXECUTE_SUCCEEDED in events
    assert events.count(LifecycleEvent.EXECUTE_READY_FOR_REVIEW) == 1  # exactly one logical transition
    assert len(client.browser_closed_calls) == 1


# ---- finding 4: RUNNER_CANCELLED vs LEASE_LOST, deterministic priority ---- #
# Phase 1C-C Pass 2A: these now call _run_execute_lifecycle directly (the
# replacement for _run_and_renew_execute) and check the returned
# _ExecuteLifecycleOutcome's `.result` field.


def test_execute_shutdown_while_running_cancels_the_write_and_reports_runner_cancelled():
    async def _hangs_forever(claimed_job, plan_hash, permit, on_ready_for_review, on_phase):
        await asyncio.Event().wait()  # never completes on its own

    client = FakeClient()
    claimed = _execute_claimed()
    started = _execute_started()
    stop_event = threading.Event()
    stop_event.set()  # shutdown already requested before this job's pipeline is entered
    lifecycle = JobPollingLifecycle(
        client, _never_called, run_execute_check=_hangs_forever, is_ready=lambda: True,
        shutdown_poll_interval_seconds=0,
    )
    outcome = asyncio.run(lifecycle._run_execute_lifecycle("secret", claimed, started, stop_event))
    assert outcome.result == "RUNNER_CANCELLED"
    assert outcome.finish_attempted is False
    assert outcome.finish_confirmed is False
    assert client.release_calls == []  # never release() once RUNNING


def test_execute_renewal_failure_cancels_the_write_and_reports_lease_lost():
    """Critical rule (item 5): unlike DRY_RUN's best-effort renewal, an
    EXECUTE renewal failure must stop mutation immediately -- the write
    task is cancelled the moment the FIRST renewal fails, never waiting for
    the write to finish on its own, and the reported outcome is LEASE_LOST
    -- distinct from an operator-driven RUNNER_CANCELLED (finding 4)."""
    async def _hangs_forever(claimed_job, plan_hash, permit, on_ready_for_review, on_phase):
        await asyncio.Event().wait()  # never completes on its own

    client = FakeClient()
    client.renew_job = lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("lease lost"))
    claimed = _execute_claimed()
    started = _execute_started()
    lifecycle = JobPollingLifecycle(
        client, _never_called, run_execute_check=_hangs_forever, is_ready=lambda: True,
        renew_interval_seconds=0, shutdown_poll_interval_seconds=0,
    )
    outcome = asyncio.run(lifecycle._run_execute_lifecycle("secret", claimed, started, threading.Event()))
    assert outcome.result == "LEASE_LOST"


def test_shutdown_takes_priority_over_a_lease_lost_at_the_same_poll():
    """Deterministic, documented priority (finding 4): stop_event is
    checked BEFORE lease_lost on every iteration, including the first --
    so when the shutdown signal is ALREADY set before this coroutine is
    even entered, RUNNER_CANCELLED wins even though renewal is ALSO primed
    to fail on its very first attempt (renew_interval_seconds=0). This
    exercises the REAL priority check in _run_execute_lifecycle, not a
    re-implementation of it."""
    async def _hangs_forever(claimed_job, plan_hash, permit, on_ready_for_review, on_phase):
        await asyncio.Event().wait()  # never completes on its own

    client = FakeClient()
    client.renew_job = lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("lease lost"))
    claimed = _execute_claimed()
    started = _execute_started()
    stop_event = threading.Event()
    stop_event.set()  # already true before this coroutine is ever entered

    lifecycle = JobPollingLifecycle(
        client, _never_called, run_execute_check=_hangs_forever, is_ready=lambda: True,
        renew_interval_seconds=0, shutdown_poll_interval_seconds=0,
    )
    outcome = asyncio.run(lifecycle._run_execute_lifecycle("secret", claimed, started, stop_event))
    assert outcome.result == "RUNNER_CANCELLED"


def test_execute_successful_renewal_never_cancels_the_write():
    client = FakeClient()
    claimed = _execute_claimed()
    started = _execute_started()

    async def _slow_write(claimed_job, plan_hash, permit, on_ready_for_review, on_phase):
        for _ in range(20):
            await asyncio.sleep(0)
        await on_ready_for_review()
        return "READY_FOR_HUMAN_REVIEW"

    lifecycle = JobPollingLifecycle(
        client, _never_called, run_execute_check=_slow_write, is_ready=lambda: True, renew_interval_seconds=0,
    )
    outcome = asyncio.run(lifecycle._run_execute_lifecycle("secret", claimed, started, threading.Event()))
    assert outcome.result == "READY_FOR_HUMAN_REVIEW"
    assert outcome.finish_attempted is True
    assert outcome.finish_confirmed is True
    assert len(client.renew_calls) > 0  # renewal genuinely ran, and never cancelled the write


# ---- Phase 1C-C Pass 2A: the execution permit (requirement B) ---- #


def test_renewal_failure_invalidates_the_permit_before_cancelling_the_write():
    """Requirement B: "the renewal failure path must invalidate the
    permit before cancelling the portal task." Observed directly: the
    write callable inspects permit.is_valid from inside its own
    CancelledError handler, which only runs once this module has already
    delivered the cancellation -- proving invalidation happened first."""
    observed = {}

    async def _observes_permit_on_cancel(claimed_job, plan_hash, permit, on_ready_for_review, on_phase):
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            observed["was_valid"] = permit.is_valid
            raise

    client = FakeClient()
    client.renew_job = lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("lease lost"))
    claimed = _execute_claimed()
    started = _execute_started()
    lifecycle = JobPollingLifecycle(
        client, _never_called, run_execute_check=_observes_permit_on_cancel, is_ready=lambda: True,
        renew_interval_seconds=0, shutdown_poll_interval_seconds=0,
    )
    outcome = asyncio.run(lifecycle._run_execute_lifecycle("secret", claimed, started, threading.Event()))
    assert outcome.result == "LEASE_LOST"
    assert observed["was_valid"] is False


def test_shutdown_invalidates_the_permit_before_cancelling_the_write():
    """Requirement F: shutdown invalidates the permit before cancelling
    execution -- same proof technique as the renewal-failure test above.
    stop_event is set from INSIDE the write callable's own first step
    (never before asyncio.run even starts) so the callable is guaranteed
    to have actually begun running -- and be parked on its own await --
    before the shutdown signal can be observed."""
    observed = {}
    stop_event = threading.Event()

    async def _observes_permit_on_cancel(claimed_job, plan_hash, permit, on_ready_for_review, on_phase):
        stop_event.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            observed["was_valid"] = permit.is_valid
            raise

    client = FakeClient()
    claimed = _execute_claimed()
    started = _execute_started()
    lifecycle = JobPollingLifecycle(
        client, _never_called, run_execute_check=_observes_permit_on_cancel, is_ready=lambda: True,
        shutdown_poll_interval_seconds=0,
    )
    outcome = asyncio.run(lifecycle._run_execute_lifecycle("secret", claimed, started, stop_event))
    assert outcome.result == "RUNNER_CANCELLED"
    assert observed["was_valid"] is False


def test_permit_is_valid_during_the_write_and_starts_activated():
    """Positive control: the permit is activated (valid) by the time the
    write callable is invoked -- start_job's own admission (the caller's)
    already happened before _run_execute_lifecycle is ever entered."""
    observed = {}

    async def _observes_permit(claimed_job, plan_hash, permit, on_ready_for_review, on_phase):
        observed["was_valid"] = permit.is_valid
        await on_ready_for_review()
        return "READY_FOR_HUMAN_REVIEW"

    client = FakeClient()
    claimed = _execute_claimed()
    started = _execute_started()
    lifecycle = JobPollingLifecycle(
        client, _never_called, run_execute_check=_observes_permit, is_ready=lambda: True,
    )
    asyncio.run(lifecycle._run_execute_lifecycle("secret", claimed, started, threading.Event()))
    assert observed["was_valid"] is True


# ---- Phase 1C-C Pass 2A: mid-flight phase/status events (item J) ---- #


def test_writing_and_verifying_phases_emit_their_own_events_in_order():
    client = FakeClient()
    client.claim_queue = [_execute_claimed()]
    client.start_result = _execute_started()
    events = []
    lifecycle = JobPollingLifecycle(
        client, _never_called, run_execute_check=_execute_ready_for_review, is_ready=lambda: True,
        on_event=events.append, wait=_stop_after(1),
    )
    lifecycle.run_forever("secret", threading.Event())
    ordered = [
        e for e in events
        if e in (
            LifecycleEvent.EXECUTE_STARTED, LifecycleEvent.EXECUTE_WRITING, LifecycleEvent.EXECUTE_VERIFYING,
            LifecycleEvent.EXECUTE_READY_FOR_REVIEW, LifecycleEvent.EXECUTE_REVIEW_IN_PROGRESS,
        )
    ]
    assert ordered == [
        LifecycleEvent.EXECUTE_STARTED, LifecycleEvent.EXECUTE_WRITING, LifecycleEvent.EXECUTE_VERIFYING,
        LifecycleEvent.EXECUTE_READY_FOR_REVIEW, LifecycleEvent.EXECUTE_REVIEW_IN_PROGRESS,
    ]


# ---- Phase 1C-C Pass 2A: no second job while the review browser is open (requirement 9) ---- #


def test_no_second_job_is_claimed_while_the_review_browser_is_open():
    """The single-threaded poll loop only claims again after
    _run_one_execute_job returns -- and that method does not return until
    the (fake) browser is closed, so a second claim while review is open
    is structurally impossible. Proven directly: the second claimable job
    is only ever reached if this worker is stopped BEFORE the first job's
    "review" ever ends."""
    review_entered = threading.Event()

    async def _blocks_in_review(claimed_job, plan_hash, permit, on_ready_for_review, on_phase):
        await on_ready_for_review()
        review_entered.set()
        await asyncio.Event().wait()  # simulates an open browser -- never returns on its own

    client = FakeClient()
    client.claim_queue = [_execute_claimed(job_id="job-1"), _execute_claimed(job_id="job-2")]
    client.start_result = _execute_started()
    stop_event = threading.Event()
    lifecycle = JobPollingLifecycle(
        client, _never_called, run_execute_check=_blocks_in_review, is_ready=lambda: True,
        shutdown_poll_interval_seconds=0,
    )
    thread = threading.Thread(target=lifecycle.run_forever, args=("secret", stop_event))
    thread.start()
    try:
        assert review_entered.wait(timeout=5.0)
        # The second job is never claimed while the first is still "under
        # review" -- claim_calls stays at exactly 1.
        assert client.claim_calls == 1
    finally:
        stop_event.set()
        thread.join(timeout=5.0)
        assert not thread.is_alive()


# ---- Phase 1C-C Pass 2A: browser-closed reporting (requirement 10-11) ---- #


def test_no_second_job_is_claimed_while_an_unconfirmed_review_browser_remains_open():
    """Requirement 7: the block on claiming a second job does not depend
    on finish having been confirmed -- an assignment still retrying an
    unconfirmed finish (browser still open, per requirement 3) is just as
    "open" as a confirmed one for this purpose."""
    client = FakeClient()
    client.finish_result = RuntimeError("still unreachable")  # never confirms on its own
    client.claim_queue = [_execute_claimed(job_id="job-1"), _execute_claimed(job_id="job-2")]
    client.start_result = _execute_started()
    attempted = threading.Event()
    original_finish_job = client.finish_job

    def _record_attempt(*args, **kwargs):
        attempted.set()
        return original_finish_job(*args, **kwargs)

    client.finish_job = _record_attempt
    stop_event = threading.Event()
    lifecycle = JobPollingLifecycle(
        client, _never_called, run_execute_check=_execute_ready_for_review, is_ready=lambda: True,
        shutdown_poll_interval_seconds=0,
    )
    thread = threading.Thread(target=lifecycle.run_forever, args=("secret", stop_event))
    thread.start()
    try:
        assert attempted.wait(timeout=5.0)
        time.sleep(0.05)  # still well inside the retry loop's own backoff wait, unconfirmed
        assert client.claim_calls == 1
    finally:
        stop_event.set()
        thread.join(timeout=5.0)
        assert not thread.is_alive()


def test_finish_unavailable_until_shutdown_retries_repeatedly_then_gives_up_cleanly():
    """Handoff-fix regression test: finish never confirms (every attempt
    fails) until an operator shutdown ends the lifecycle -- genuinely
    retried more than once (never single-attempt-then-give-up), no
    READY/REVIEW event ever fires, the browser still closes (via
    run_workstation_execute_write's own structural guarantee -- modelled
    here by the fake simply returning once cancelled), and the retry
    loop does not continue forever once stopped."""
    client = FakeClient()
    claimed = _execute_claimed()
    started = _execute_started()
    attempt_count = {"n": 0}

    def _always_fails(*args, **kwargs):
        attempt_count["n"] += 1
        raise ConnectionError("still unreachable")

    client.finish_job = _always_fails
    events = []
    lifecycle = JobPollingLifecycle(
        client, _never_called, run_execute_check=_execute_ready_for_review, is_ready=lambda: True,
        on_event=events.append, renew_interval_seconds=0, shutdown_poll_interval_seconds=0,
    )

    async def _scenario():
        stop_event = threading.Event()
        task = asyncio.ensure_future(lifecycle._run_execute_lifecycle("secret", claimed, started, stop_event))
        # Let several real retry attempts happen (small, real backoff --
        # bounded and brief since the exponential cap starts at 2s and
        # this test only needs to observe more than one attempt).
        while attempt_count["n"] < 2:
            await asyncio.sleep(0.01)
        stop_event.set()
        return await task

    outcome = asyncio.run(_scenario())
    assert attempt_count["n"] >= 2  # genuinely retried, not a single attempt
    assert outcome.result == "RUNNER_CANCELLED"
    assert outcome.finish_attempted is True
    assert outcome.finish_confirmed is False
    assert outcome.browser_closed is True
    assert LifecycleEvent.EXECUTE_READY_FOR_REVIEW not in events
    assert LifecycleEvent.EXECUTE_REVIEW_IN_PROGRESS not in events


def test_shutdown_while_finish_is_in_flight_awaits_the_bounded_result_and_confirms_it_was_committed():
    """Handoff-fix requirement 2: a shutdown that lands WHILE a finish
    attempt is genuinely in flight (blocked on what stands in for the
    bounded HTTP call) does not abandon it -- the shielded call is
    awaited to its real conclusion before the cancellation is allowed to
    propagate. Here the in-flight call ultimately succeeds (the server
    committed it) -- finish_confirmed must reflect that TRUE outcome,
    never a guess made the instant stop_event was observed."""
    client = FakeClient()
    claimed = _execute_claimed()
    started = _execute_started()
    entered_finish = threading.Event()
    release_finish = threading.Event()

    def _blocking_then_confirms(runner_secret, *, job_id, claim_token, generation, result):
        entered_finish.set()
        assert release_finish.wait(timeout=5.0)
        return FakeFinishResult(status="SUCCEEDED", job_status="READY_FOR_HUMAN_REVIEW")

    client.finish_job = _blocking_then_confirms
    lifecycle = JobPollingLifecycle(
        client, _never_called, run_execute_check=_execute_ready_for_review, is_ready=lambda: True,
        shutdown_poll_interval_seconds=0,
    )

    async def _scenario():
        stop_event = threading.Event()
        task = asyncio.ensure_future(lifecycle._run_execute_lifecycle("secret", claimed, started, stop_event))
        while not entered_finish.is_set():
            await asyncio.sleep(0)
        stop_event.set()  # shutdown lands WHILE the request is genuinely in flight
        await asyncio.sleep(0.05)  # let the outer poll loop observe it and deliver the cancellation
        release_finish.set()  # only now does the "server" respond -- it confirms
        return await task

    outcome = asyncio.run(_scenario())
    assert outcome.result == "RUNNER_CANCELLED"
    assert outcome.finish_attempted is True
    assert outcome.finish_confirmed is True  # the TRUE, awaited outcome -- never assumed False on cancellation alone


def test_shutdown_while_finish_is_in_flight_and_it_ultimately_fails_never_reports_confirmed():
    """Same shape as the test above, but the in-flight call ultimately
    fails (never committed) -- finish_confirmed must stay False, and (via
    _run_one_execute_job's own gating, exercised separately) browser-
    closed must never be sent for it."""
    client = FakeClient()
    claimed = _execute_claimed()
    started = _execute_started()
    entered_finish = threading.Event()
    release_finish = threading.Event()

    def _blocking_then_fails(runner_secret, *, job_id, claim_token, generation, result):
        entered_finish.set()
        assert release_finish.wait(timeout=5.0)
        raise ConnectionError("never actually committed")

    client.finish_job = _blocking_then_fails
    lifecycle = JobPollingLifecycle(
        client, _never_called, run_execute_check=_execute_ready_for_review, is_ready=lambda: True,
        shutdown_poll_interval_seconds=0,
    )

    async def _scenario():
        stop_event = threading.Event()
        task = asyncio.ensure_future(lifecycle._run_execute_lifecycle("secret", claimed, started, stop_event))
        while not entered_finish.is_set():
            await asyncio.sleep(0)
        stop_event.set()
        await asyncio.sleep(0.05)
        release_finish.set()
        return await task

    outcome = asyncio.run(_scenario())
    assert outcome.result == "RUNNER_CANCELLED"
    assert outcome.finish_attempted is True
    assert outcome.finish_confirmed is False


def test_browser_closed_is_reported_exactly_once_on_first_success():
    client = FakeClient()
    client.claim_queue = [_execute_claimed()]
    client.start_result = _execute_started()
    lifecycle = JobPollingLifecycle(
        client, _never_called, run_execute_check=_execute_ready_for_review, is_ready=lambda: True,
        wait=_stop_after(1),
    )
    lifecycle.run_forever("secret", threading.Event())
    assert len(client.browser_closed_calls) == 1


def test_browser_closed_reporting_retries_with_bounded_backoff_then_succeeds():
    client = FakeClient()
    attempts = {"count": 0}
    real_report = client.report_execute_review_browser_closed

    def _fails_twice_then_succeeds(*args, **kwargs):
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise ConnectionError("unreachable")
        return real_report(*args, **kwargs)

    client.report_execute_review_browser_closed = _fails_twice_then_succeeds
    waits = []

    def _fast_wait(event, timeout):
        waits.append(timeout)
        return event.wait(0)  # never actually sleeps -- bounded backoff, never a real delay in this test

    lifecycle = JobPollingLifecycle(
        client, _never_called, run_execute_check=_execute_ready_for_review, is_ready=lambda: True,
        wait=_fast_wait,
    )
    stop_event = threading.Event()
    lifecycle._report_browser_closed_with_retry("secret", _execute_claimed(), stop_event)
    assert attempts["count"] == 3
    assert len(client.browser_closed_calls) == 1
    # Exponential, bounded backoff was actually used between attempts --
    # never a fixed/no delay and never unbounded growth.
    assert waits == [_INITIAL_BACKOFF_SECONDS, _INITIAL_BACKOFF_SECONDS * 2]


def test_browser_closed_reporting_stops_retrying_once_the_runner_is_stopped():
    client = FakeClient()
    client.report_execute_review_browser_closed = lambda *a, **kw: (_ for _ in ()).throw(ConnectionError("down"))
    stop_event = threading.Event()

    def _wait_then_stop(event, timeout):
        stop_event.set()
        return True

    lifecycle = JobPollingLifecycle(
        client, _never_called, run_execute_check=_execute_ready_for_review, is_ready=lambda: True,
        wait=_wait_then_stop,
    )
    # Must return (not hang) once stop_event is observed, and must never
    # raise even though every attempt failed.
    lifecycle._report_browser_closed_with_retry("secret", _execute_claimed(), stop_event)
    assert client.browser_closed_calls == []


def test_browser_closed_makes_exactly_one_immediate_attempt_when_stop_event_is_already_set():
    """Handoff-fix requirement 4: shutdown AFTER a confirmed finish --
    stop_event is already True the moment this is called (matching
    _run_one_execute_job's own post-asyncio.run() call site after a
    shutdown-driven cancellation). Exactly one immediate fenced attempt
    is made regardless -- never suppressed by the already-set stop_event
    -- and if that attempt fails, no further retry follows."""
    client = FakeClient()
    stop_event = threading.Event()
    stop_event.set()  # ALREADY set before the first attempt is ever made
    waits = []
    lifecycle = JobPollingLifecycle(
        client, _never_called, run_execute_check=_execute_ready_for_review, is_ready=lambda: True,
        wait=lambda event, timeout: waits.append(timeout) or True,
    )
    lifecycle._report_browser_closed_with_retry("secret", _execute_claimed(), stop_event)
    assert len(client.browser_closed_calls) == 1  # the one required attempt, made despite stop_event
    assert waits == []  # never retried -- no backoff wait was ever needed or taken


def test_browser_closed_stops_after_one_failed_attempt_when_stop_event_is_already_set():
    client = FakeClient()
    client.report_execute_review_browser_closed = lambda *a, **kw: (_ for _ in ()).throw(ConnectionError("down"))
    stop_event = threading.Event()
    stop_event.set()
    waits = []
    lifecycle = JobPollingLifecycle(
        client, _never_called, run_execute_check=_execute_ready_for_review, is_ready=lambda: True,
        wait=lambda event, timeout: waits.append(timeout) or True,
    )
    lifecycle._report_browser_closed_with_retry("secret", _execute_claimed(), stop_event)
    assert waits == []  # the ONE required attempt was made and failed -- never retried during shutdown


def test_a_duplicate_browser_closed_report_is_safe_and_never_marks_completion_itself():
    """The server's own endpoint is idempotent (AWAITING_HUMAN_CONFIRMATION
    or a repeated HUMAN_CONFIRMED_COMPLETE) -- this worker never inspects
    the response to decide "human completion" itself (requirement E)."""
    client = FakeClient()
    client.report_execute_review_browser_closed = lambda *a, **kw: client.browser_closed_calls.append("dup") or object()
    lifecycle = JobPollingLifecycle(client, _never_called, run_execute_check=_execute_ready_for_review, is_ready=lambda: True)
    stop_event = threading.Event()
    lifecycle._report_browser_closed_with_retry("secret", _execute_claimed(), stop_event)
    lifecycle._report_browser_closed_with_retry("secret", _execute_claimed(), stop_event)
    assert client.browser_closed_calls == ["dup", "dup"]  # each call is independently safe/idempotent server-side


def test_join_is_never_called_on_an_unstarted_thread_object():
    """The exact failure mode the task calls out: a concurrent stop() must
    never observe a Thread that exists but was never actually started
    (Thread.join() raises RuntimeError on one). Run many times under
    concurrent start()/stop() pressure -- a single reproduction would be a
    real bug."""
    for _ in range(50):
        lifecycle = _CountingLifecycle()
        worker = JobPollingWorker(lifecycle, "secret")
        starter = threading.Thread(target=worker.start)
        starter.start()
        # stop() races start() with no synchronization -- if it ever sees
        # a published-but-unstarted Thread, .join() inside stop() raises
        # and this test fails with that RuntimeError instead of returning.
        result = worker.stop(timeout=5.0)
        starter.join(timeout=5.0)
        assert result is True
