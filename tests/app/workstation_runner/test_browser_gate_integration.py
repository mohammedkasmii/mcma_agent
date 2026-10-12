"""The shared BrowserOperationGate in the two EXISTING browser owners: the
saved-session BrowserSessionWorker and the JobPollingLifecycle. While the
notification-onboarding worker owns the gate neither may start a browser
operation / claim a job, and each holds the gate only while it works."""

import threading
import time

from mcma.app.workstation_runner.browser_gate import (
    OWNER_JOB, OWNER_ONBOARDING, OWNER_SESSION, BrowserOperationGate,
)
from mcma.app.workstation_runner.browser_worker import BrowserSessionWorker
from mcma.app.workstation_runner.job_worker import JobPollingLifecycle
from mcma.app.workstation_runner.sessions import WorkstationSessionManager

from tests.app.workstation_runner.test_job_worker import FakeClaimedJob, FakeClient, _matches, _stop_after

OUJDA = "acct-mcma-oujda"


def _until(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


# ------------------------------------------------------------ job worker ------------------------------------------------------------ #


def test_job_worker_does_not_claim_while_onboarding_holds_the_gate():
    gate = BrowserOperationGate()
    assert gate.try_acquire(OWNER_ONBOARDING)
    client = FakeClient()
    client.claim_queue.append(FakeClaimedJob())
    lifecycle = JobPollingLifecycle(client, _matches, is_ready=lambda: True, wait=_stop_after(3), gate=gate)
    lifecycle.run_forever("secret", threading.Event())
    assert client.claim_calls == 0
    assert gate.holder() == OWNER_ONBOARDING            # never disturbed


def test_job_worker_holds_the_gate_only_while_claiming_and_working():
    gate = BrowserOperationGate()
    client = FakeClient()
    seen = []

    async def executor(claimed, plan_hash):
        seen.append(gate.holder())
        return "IDENTITY_MATCHED"

    client.claim_queue.append(FakeClaimedJob())
    lifecycle = JobPollingLifecycle(client, executor, is_ready=lambda: True, wait=_stop_after(2), gate=gate)
    lifecycle.run_forever("secret", threading.Event())
    assert seen == [OWNER_JOB]
    assert gate.holder() is None


def test_job_worker_releases_the_gate_when_claim_fails_or_returns_nothing():
    gate = BrowserOperationGate()
    client = FakeClient()
    client.claim_queue.append(RuntimeError("boom"))
    lifecycle = JobPollingLifecycle(client, _matches, is_ready=lambda: True, wait=_stop_after(2), gate=gate)
    lifecycle.run_forever("secret", threading.Event())
    assert client.claim_calls == 2 and gate.holder() is None


def test_job_worker_without_a_gate_is_unchanged():
    client = FakeClient()
    lifecycle = JobPollingLifecycle(client, _matches, is_ready=lambda: True, wait=_stop_after(2))
    lifecycle.run_forever("secret", threading.Event())
    assert client.claim_calls == 2


# ------------------------------------------------------------ session worker ------------------------------------------------------------ #


def _session_worker(gate, login):
    manager = WorkstationSessionManager(has_saved_session=lambda a: False)
    manager.reconcile_allowed_accounts((OUJDA,))

    class Store:
        def load(self, a): return None
        def save(self, a, s): pass
        def clear(self, a): pass

    async def verify(account_id, state):
        raise AssertionError("not used")

    return BrowserSessionWorker(
        session_manager=manager, session_store=Store(), perform_manual_login=login,
        verify_saved_session=verify, gate=gate,
    )


def test_session_worker_skips_login_while_onboarding_holds_the_gate():
    gate = BrowserOperationGate()
    assert gate.try_acquire(OWNER_ONBOARDING)
    started = threading.Event()

    async def login(account_id):
        started.set()
        raise RuntimeError("must not run")

    worker = _session_worker(gate, login)
    worker.start()
    try:
        assert worker.request_login(OUJDA) is True            # admitted...
        assert _until(lambda: not worker._pending_or_active_accounts)   # ...then dropped, explicitly
        assert not started.is_set()
        assert gate.holder() == OWNER_ONBOARDING
        assert worker.request_login(OUJDA) is True            # and the account is not stuck busy
    finally:
        assert worker.stop(timeout=2.0)


def test_session_worker_holds_the_gate_during_login_and_releases_after():
    gate = BrowserOperationGate()
    during = []
    done = threading.Event()

    class Material:
        def consume_for_handoff(self):
            return {"cookies": [], "origins": []}

    async def login(account_id):
        during.append(gate.holder())
        done.set()
        return Material()

    worker = _session_worker(gate, login)
    worker.start()
    try:
        assert worker.request_login(OUJDA) is True
        assert done.wait(2.0)
        assert during == [OWNER_SESSION]
        assert _until(lambda: gate.holder() is None)
    finally:
        assert worker.stop(timeout=2.0)
