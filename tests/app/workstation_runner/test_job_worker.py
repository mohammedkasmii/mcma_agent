"""mcma.app.workstation_runner.job_worker -- Phase 1C-B, item D. Unit-level:
the RegistryHttpClient and the executor are both plain fakes/coroutines,
never real HTTP/Playwright. No real sleeps -- `wait` is injected for the
outer poll/backoff loop, and the inner shutdown-watch loop's
`asyncio.sleep(0)`-style yields (via a zero `shutdown_poll_interval_seconds`)
are pure cooperative yields, never a wall-clock delay."""

import asyncio
import threading
from dataclasses import dataclass
from typing import Optional

from mcma.app.workstation_runner.job_worker import JobPollingLifecycle, JobPollingWorker, LifecycleEvent


@dataclass(frozen=True)
class FakeClaimedJob:
    job_id: str = "job-1"
    claim_token: str = "mcma_ct_" + "t" * 40
    generation: int = 1


@dataclass(frozen=True)
class FakeStartedJob:
    status: str
    plan_hash: Optional[str] = None


class FakeClient:
    def __init__(self):
        self.claim_queue: list = []
        self.claim_calls = 0
        self.start_calls: list = []
        self.start_result = FakeStartedJob(status="RUNNING", plan_hash="h" * 64)
        self.renew_calls: list = []
        self.release_calls: list = []
        self.finish_calls: list = []
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
    client.start_result = FakeStartedJob(status="NEEDS_REVIEW", plan_hash=None)
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
