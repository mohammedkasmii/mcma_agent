"""Pilot-runner correction -- a fast, LOCAL (non-egress) proof of
mcma.execution.runner's EXECUTE composition: state-before-I/O ordering,
browser-close observation registered before the first mutation, shared-
account exclusivity enforced before any context exists, lease lifecycle
across human handoff, and no-leak teardown on every error path.

Until now the ONLY test exercising process_one_planned_execute was
test_runner_live_chromium_proof.py, which is marked egress_proof +
requires_egress_isolation and is therefore deselected in every ordinary
run -- so the runner's own orchestration was effectively unverified in
CI. This file closes that gap the same way test_dry_run_fake_browser.py
already does for DRY_RUN: real SQLite, real vault-backed session, real
account lease, real run_execute_write_async composition, with only the
portal boundary itself faked.

The seam is mcma.execution.runner.open_verified_writer, monkeypatched in
THIS module's tests only -- there is deliberately no production hook for
substituting a writer. Faking a VerifiedMissionWriter through a
production seam would let a caller supply a writer that never passed
require_mcma_writer_account (MAMDA read-only enforcement, layer 3); the
real construction sequence stays covered by the live-Chromium proofs.
"""

import asyncio

import pytest

from mcma.execution.browser_handoff import ActiveReviewRegistry
from mcma.execution.jobs import confirm_review_completed
from mcma.persistence.repositories.jobs import AutomationJobsRepository
from mcma.execution.runner import (
    RunnerConfig,
    _heartbeat_forever,
    process_one_planned_execute,
    process_queued_planned_execute_jobs,
)
from mcma.persistence.leases import LeaseInvalid, LeaseNotHeld, acquire_lease
from mcma.portal.vault import TestOnlyAclVerifier as _AclVerifier
from mcma.portal.vault import store_session
from runner_test_support import (
    ALLOWED_HOST,
    INSTANCE_ID,
    MCMA_OUJDA_ACCOUNT_ID,
    MODE_NORMAL_TYPED_INPUT,
    conn,  # noqa: F401
    crypto_backend,  # noqa: F401
    encryptor,  # noqa: F401
    run_async,
    seed_mcma_oujda_session,
    vault_dir,  # noqa: F401
)
from test_runner_live_chromium_proof import _execute_job_planned

MCMA_NADOR_ACCOUNT_ID = "acct-mcma-nador"

# The complete set of VerifiedMissionWriter methods the runner is allowed
# to drive. Valider/Cloture and every other final-action control is
# absent BY CONSTRUCTION -- no such method exists on the writer at all --
# and test_runner_never_touches_a_final_action asserts the runner stays
# inside this set even as the write phases are refactored.
_APPROVED_WRITER_CALLS = frozenset(
    {
        "add_normal_row",
        "edit_conventionne_row",
        "verify_row",
        "fill_form_fields",
        "verify_form_fields",
        "trigger_native_recalc",
        "verify_financial_summary",
        "close",
        "register_close_callback",
    }
)
_MUTATING_WRITER_CALLS = frozenset(
    {"add_normal_row", "edit_conventionne_row", "fill_form_fields", "trigger_native_recalc"}
)


class FakeWriter:
    """Structurally a VerifiedMissionWriter for the subset the runner
    drives, including the is_closed/is_terminally_aborted properties the
    runner uses to tell its OWN teardown apart from the employee closing
    the window. `on_call` lets a test observe or interfere at any step."""

    def __init__(self, *, on_call=None):
        self.calls = []
        self._on_call = on_call
        self._close_callbacks = []
        self._closed = False
        self._terminally_aborted = False

    @property
    def is_closed(self):
        return self._closed

    @property
    def is_terminally_aborted(self):
        return self._terminally_aborted

    def register_close_callback(self, on_close):
        self.calls.append("register_close_callback")
        self._close_callbacks.append(on_close)

    async def close(self):
        self.calls.append("close")
        self._closed = True

    def simulate_external_close(self):
        """The employee closing the review window: the context's close
        event fires while this writer is neither closed nor aborted by
        us."""
        for callback in list(self._close_callbacks):
            callback()

    def simulate_terminal_abort(self):
        """What VerifiedMissionWriter._terminal_abort does: mark the
        writer aborted BEFORE the context close event fires."""
        self._terminally_aborted = True
        for callback in list(self._close_callbacks):
            callback()

    async def _step(self, name, *args):
        self.calls.append(name)
        if self._on_call is not None:
            result = self._on_call(name, self)
            if asyncio.iscoroutine(result):
                await result

    async def add_normal_row(self, rubrique_id):
        await self._step("add_normal_row", rubrique_id)

    async def edit_conventionne_row(self, rubrique_id):
        await self._step("edit_conventionne_row", rubrique_id)

    async def verify_row(self, rubrique_id):
        await self._step("verify_row", rubrique_id)

    async def fill_form_fields(self):
        await self._step("fill_form_fields")

    async def verify_form_fields(self):
        await self._step("verify_form_fields")

    async def trigger_native_recalc(self):
        await self._step("trigger_native_recalc")

    async def verify_financial_summary(self):
        await self._step("verify_financial_summary")


def _install_fake_writer(monkeypatch, writer, *, record_opens=None):
    async def _fake_open_verified_writer(*args, **kwargs):
        if record_opens is not None:
            record_opens.append(kwargs.get("writer_account"))
        return writer

    monkeypatch.setattr(
        "mcma.execution.runner.open_verified_writer", _fake_open_verified_writer
    )


def _cfg(vault_dir, crypto_backend, registry=None) -> RunnerConfig:
    return RunnerConfig(
        instance_id=INSTANCE_ID,
        allowed_host=ALLOWED_HOST,
        vault_dir=vault_dir,
        crypto_backend=crypto_backend,
        active_review_registry=registry or ActiveReviewRegistry(),
    )


def _seed_session_for(conn, account_id, vault_dir, crypto_backend):
    lease = acquire_lease(conn, account_id, INSTANCE_ID)
    try:
        store_session(
            conn, lease, account_id, b'{"cookies": [], "origins": []}',
            vault_dir=vault_dir, backend=crypto_backend, acl_verifier=_AclVerifier(True),
        )
    finally:
        lease.release()


def _status(conn, job_id):
    return AutomationJobsRepository(conn).get(job_id)["status"]


def _lease_row(conn, account_id):
    return conn.execute(
        "SELECT * FROM account_leases WHERE account_id=?", (account_id,)
    ).fetchone()


def _run_execute(conn, job_id, cfg, encryptor, on_browser_closed=None):
    return run_async(
        process_one_planned_execute(
            conn, job_id, browser=object(), cfg=cfg, encryptor=encryptor,
            on_browser_closed=on_browser_closed,
        )
    )


# --------------------------------------------------------------------- #
# 1. State before I/O, and close observation live before the first write
# --------------------------------------------------------------------- #


def test_persisted_status_is_already_writing_at_the_first_mutation(
    conn, vault_dir, crypto_backend, encryptor, monkeypatch
):
    """Requirement 1: the job row must ALREADY say WRITING when the first
    mutation happens, VERIFYING when the first read-back happens, and the
    browser-close observer must already be registered before either --
    not caught up afterwards."""
    seed_mcma_oujda_session(conn, vault_dir, crypto_backend)
    job_id = _execute_job_planned(conn, encryptor, typed_input=MODE_NORMAL_TYPED_INPUT, key="order-1")
    cfg = _cfg(vault_dir, crypto_backend)
    observed = {}

    def _observe(name, writer):
        if name in _MUTATING_WRITER_CALLS:
            observed.setdefault("status_at_first_mutation", _status(conn, job_id))
            observed.setdefault(
                "registered_at_first_mutation", cfg.active_review_registry.get(job_id) is not None
            )
        if name.startswith("verify_"):
            observed.setdefault("status_at_first_read_back", _status(conn, job_id))

    writer = FakeWriter(on_call=_observe)
    _install_fake_writer(monkeypatch, writer)

    assert _run_execute(conn, job_id, cfg, encryptor) == "READY_FOR_HUMAN_REVIEW"
    assert observed["status_at_first_mutation"] == "WRITING"
    assert observed["status_at_first_read_back"] == "VERIFYING"
    # Requirement 3: observation is subscribed BEFORE writes begin.
    assert observed["registered_at_first_mutation"] is True
    assert writer.calls.index("register_close_callback") < min(
        writer.calls.index(name) for name in writer.calls if name in _MUTATING_WRITER_CALLS
    )


def test_runner_never_touches_a_final_action(
    conn, vault_dir, crypto_backend, encryptor, monkeypatch
):
    """Requirement: no final-action selector or endpoint is called or
    inspected. The runner drives only the approved write/read-back
    surface; Valider/Cloture is the employee's, in their own browser."""
    seed_mcma_oujda_session(conn, vault_dir, crypto_backend)
    job_id = _execute_job_planned(conn, encryptor, typed_input=MODE_NORMAL_TYPED_INPUT, key="final-1")
    writer = FakeWriter()
    _install_fake_writer(monkeypatch, writer)

    _run_execute(conn, job_id, _cfg(vault_dir, crypto_backend), encryptor)

    assert set(writer.calls) <= _APPROVED_WRITER_CALLS
    forbidden = ("valid", "clot", "cloture", "submit", "final")
    assert not [c for c in writer.calls if any(f in c.lower() for f in forbidden)]


# --------------------------------------------------------------------- #
# 2/3. Browser closure, before and after READY
# --------------------------------------------------------------------- #


def test_browser_closed_before_ready_lands_interrupted_and_releases_the_lease(
    conn, vault_dir, crypto_backend, encryptor, monkeypatch
):
    """Requirement 3: an employee closing the window mid-write is
    observed (it would not have been, when registration happened only
    after READY) and fails closed to INTERRUPTED_NEEDS_HUMAN_REVIEW --
    never WRITE_ABORTED-over-INTERRUPTED, and never a success."""
    seed_mcma_oujda_session(conn, vault_dir, crypto_backend)
    job_id = _execute_job_planned(conn, encryptor, typed_input=MODE_NORMAL_TYPED_INPUT, key="close-early")
    closed_notifications = []

    def _close_during_first_mutation(name, writer):
        if name == "add_normal_row" and not writer.is_closed:
            writer.simulate_external_close()
            raise RuntimeError("context closed mid-write")

    writer = FakeWriter(on_call=_close_during_first_mutation)
    _install_fake_writer(monkeypatch, writer)

    status = _run_execute(
        conn, job_id, _cfg(vault_dir, crypto_backend), encryptor,
        on_browser_closed=closed_notifications.append,
    )

    assert _status(conn, job_id) == "INTERRUPTED_NEEDS_HUMAN_REVIEW"
    assert status == "INTERRUPTED_NEEDS_HUMAN_REVIEW"
    assert closed_notifications == [job_id]
    # Nothing further will run, so the lease must not outlive the attempt.
    assert _lease_row(conn, MCMA_OUJDA_ACCOUNT_ID) is None


def test_browser_closed_after_ready_awaits_confirmation_and_keeps_the_lease_held(
    conn, vault_dir, crypto_backend, encryptor, monkeypatch
):
    """Requirement 5: closure after READY is expected human behaviour --
    AWAITING_HUMAN_CONFIRMATION, never success -- and the lease stays
    held so no second job can take the shared account while the review is
    still open."""
    seed_mcma_oujda_session(conn, vault_dir, crypto_backend)
    job_id = _execute_job_planned(conn, encryptor, typed_input=MODE_NORMAL_TYPED_INPUT, key="close-late")
    writer = FakeWriter()
    _install_fake_writer(monkeypatch, writer)

    assert _run_execute(conn, job_id, _cfg(vault_dir, crypto_backend), encryptor) == "READY_FOR_HUMAN_REVIEW"
    writer.simulate_external_close()

    assert _status(conn, job_id) == "AWAITING_HUMAN_CONFIRMATION"
    assert _lease_row(conn, MCMA_OUJDA_ACCOUNT_ID) is not None
    with pytest.raises(LeaseNotHeld):
        acquire_lease(conn, MCMA_OUJDA_ACCOUNT_ID, "another-instance", owner_job_id="another-job")


def test_internal_abort_and_close_produce_exactly_one_outcome(
    conn, vault_dir, crypto_backend, encryptor, monkeypatch
):
    """Requirement 3: a writer that terminally aborts itself closes its
    own context, which fires the same close event an employee would. The
    two must not both record an outcome -- the write path's WRITE_ABORTED
    stands, and the close callback stays out of it."""
    seed_mcma_oujda_session(conn, vault_dir, crypto_backend)
    job_id = _execute_job_planned(conn, encryptor, typed_input=MODE_NORMAL_TYPED_INPUT, key="abort-1")
    closed_notifications = []

    def _abort_during_first_mutation(name, writer):
        if name == "add_normal_row":
            writer.simulate_terminal_abort()
            raise RuntimeError("row write uncertain")

    writer = FakeWriter(on_call=_abort_during_first_mutation)
    _install_fake_writer(monkeypatch, writer)

    status = _run_execute(
        conn, job_id, _cfg(vault_dir, crypto_backend), encryptor,
        on_browser_closed=closed_notifications.append,
    )

    assert status == "WRITE_ABORTED"
    assert _status(conn, job_id) == "WRITE_ABORTED"
    assert closed_notifications == []
    assert _lease_row(conn, MCMA_OUJDA_ACCOUNT_ID) is None


def test_read_back_failure_is_reported_as_a_verify_failure_not_a_write_failure(
    conn, vault_dir, crypto_backend, encryptor, monkeypatch
):
    seed_mcma_oujda_session(conn, vault_dir, crypto_backend)
    job_id = _execute_job_planned(conn, encryptor, typed_input=MODE_NORMAL_TYPED_INPUT, key="verify-fail")

    def _fail_read_back(name, writer):
        if name == "verify_row":
            raise RuntimeError("read-back mismatch")

    _install_fake_writer(monkeypatch, FakeWriter(on_call=_fail_read_back))

    assert _run_execute(conn, job_id, _cfg(vault_dir, crypto_backend), encryptor) == "WRITE_ABORTED"
    row = AutomationJobsRepository(conn).get(job_id)
    assert row["reason_code"] == "VERIFY_EXCEPTION_RuntimeError"


# --------------------------------------------------------------------- #
# 4. One active form job per shared account
# --------------------------------------------------------------------- #


def test_second_job_on_the_same_account_is_rejected_before_any_context_or_mutation(
    conn, vault_dir, crypto_backend, encryptor, monkeypatch
):
    """Requirement 4: the refusal must happen BEFORE a second browser
    context is created and before any mutation -- previously the registry
    only objected at the very end, after the second job had already
    written to the shared account."""
    seed_mcma_oujda_session(conn, vault_dir, crypto_backend)
    registry = ActiveReviewRegistry()
    cfg = _cfg(vault_dir, crypto_backend, registry)

    first_id = _execute_job_planned(conn, encryptor, typed_input=MODE_NORMAL_TYPED_INPUT, key="dup-1")
    _install_fake_writer(monkeypatch, FakeWriter())
    assert _run_execute(conn, first_id, cfg, encryptor) == "READY_FOR_HUMAN_REVIEW"

    second_id = _execute_job_planned(conn, encryptor, typed_input=MODE_NORMAL_TYPED_INPUT, key="dup-2")
    second_writer = FakeWriter()
    opens = []
    _install_fake_writer(monkeypatch, second_writer, record_opens=opens)

    assert _run_execute(conn, second_id, cfg, encryptor) == "IDENTITY_FAILED"
    row = AutomationJobsRepository(conn).get(second_id)
    # Contention, recorded as contention -- not as an identity mismatch.
    assert row["reason_code"] == "ACCOUNT_BUSY_ANOTHER_JOB_ACTIVE"
    assert opens == []          # no second browser context was ever created
    assert second_writer.calls == []   # and nothing was mutated
    # The first job's session is untouched by the second's rejection.
    assert registry.get(first_id) is not None
    assert _lease_row(conn, MCMA_OUJDA_ACCOUNT_ID)["owner_job_id"] == first_id


def test_a_different_account_remains_independently_usable(
    conn, vault_dir, crypto_backend, encryptor, monkeypatch
):
    """Exclusivity is per shared account, not global: a job on another
    account runs normally while the first account is mid-review."""
    seed_mcma_oujda_session(conn, vault_dir, crypto_backend)
    _seed_session_for(conn, MCMA_NADOR_ACCOUNT_ID, vault_dir, crypto_backend)
    registry = ActiveReviewRegistry()
    cfg = _cfg(vault_dir, crypto_backend, registry)

    first_id = _execute_job_planned(conn, encryptor, typed_input=MODE_NORMAL_TYPED_INPUT, key="acct-1")
    _install_fake_writer(monkeypatch, FakeWriter())
    assert _run_execute(conn, first_id, cfg, encryptor) == "READY_FOR_HUMAN_REVIEW"

    other_id = _execute_job_planned(
        conn, encryptor, typed_input=MODE_NORMAL_TYPED_INPUT, key="acct-2",
        account_id=MCMA_NADOR_ACCOUNT_ID,
    )
    other_writer = FakeWriter()
    _install_fake_writer(monkeypatch, other_writer)

    assert _run_execute(conn, other_id, cfg, encryptor) == "READY_FOR_HUMAN_REVIEW"
    assert _lease_row(conn, MCMA_NADOR_ACCOUNT_ID)["owner_job_id"] == other_id
    assert _lease_row(conn, MCMA_OUJDA_ACCOUNT_ID)["owner_job_id"] == first_id
    assert registry.active_job_for_account(MCMA_OUJDA_ACCOUNT_ID) == first_id
    assert registry.active_job_for_account(MCMA_NADOR_ACCOUNT_ID) == other_id


# --------------------------------------------------------------------- #
# 5. Lease lifecycle across the handoff
# --------------------------------------------------------------------- #


def test_confirmation_releases_the_lease_and_frees_the_account(
    conn, vault_dir, crypto_backend, encryptor, monkeypatch
):
    seed_mcma_oujda_session(conn, vault_dir, crypto_backend)
    registry = ActiveReviewRegistry()
    cfg = _cfg(vault_dir, crypto_backend, registry)
    job_id = _execute_job_planned(conn, encryptor, typed_input=MODE_NORMAL_TYPED_INPUT, key="confirm-1")
    writer = FakeWriter()
    _install_fake_writer(monkeypatch, writer)

    _run_execute(conn, job_id, cfg, encryptor)
    writer.simulate_external_close()
    assert _status(conn, job_id) == "AWAITING_HUMAN_CONFIRMATION"

    # The API layer wires no in-memory handle -- the fenced, job-owned
    # fallback is what must free the account here.
    assert confirm_review_completed(
        conn, job_id, confirmed_by_user_id="operator-1"
    ) == "HUMAN_CONFIRMED_COMPLETE"
    assert _lease_row(conn, MCMA_OUJDA_ACCOUNT_ID) is None
    # The account is genuinely usable again.
    acquire_lease(conn, MCMA_OUJDA_ACCOUNT_ID, "next-instance", owner_job_id="next-job")


def test_heartbeat_prevents_lease_expiry_during_an_open_review(conn):
    """Requirement 5: without renewal the fixed TTL lapses out from under
    an open review. With it, the lease stays valid past its original
    expiry."""
    lease = acquire_lease(conn, MCMA_OUJDA_ACCOUNT_ID, INSTANCE_ID, owner_job_id="hb-job", ttl_seconds=1)
    first_expiry = _lease_row(conn, MCMA_OUJDA_ACCOUNT_ID)["expires_at"]

    async def _run():
        task = asyncio.create_task(_heartbeat_forever(lease, interval_seconds=0.05))
        await asyncio.sleep(0.3)
        renewed = _lease_row(conn, MCMA_OUJDA_ACCOUNT_ID)["expires_at"]
        await lease.assert_valid()
        task.cancel()
        return renewed

    renewed_expiry = run_async(_run())
    assert renewed_expiry > first_expiry
    # And another job still cannot take it while it is being renewed.
    with pytest.raises(LeaseNotHeld):
        acquire_lease(conn, MCMA_OUJDA_ACCOUNT_ID, "other-instance", owner_job_id="other-job")


class _CountingLease:
    """Records renewals so the cap can be proven by count, not by
    absence of a hang."""

    def __init__(self):
        self.account_id = "counted-account"
        self.heartbeats = 0

    def heartbeat(self):
        self.heartbeats += 1


def test_heartbeat_stops_renewing_at_the_maximum_hold():
    """The renewal is bounded: an abandoned review browser must not pin a
    shared account forever, or release_stale_leases (which reclaims by
    expires_at) could never recover it. Five intervals fit inside the
    cap, so the task must renew five times and then RETURN on its own --
    not keep going, and not have to be cancelled."""
    lease = _CountingLease()

    run_async(_heartbeat_forever(lease, interval_seconds=0.01, max_hold_seconds=0.05))

    assert lease.heartbeats == 5


def test_heartbeat_gives_up_when_the_lease_was_taken_by_someone_else(conn):
    """A lost lease is not papered over: the task stops rather than
    re-acquiring an account another owner now legitimately holds."""

    class _LostLease:
        account_id = MCMA_OUJDA_ACCOUNT_ID

        def __init__(self):
            self.heartbeats = 0

        def heartbeat(self):
            self.heartbeats += 1
            raise LeaseInvalid(self.account_id)

    lease = _LostLease()
    run_async(_heartbeat_forever(lease, interval_seconds=0.01, max_hold_seconds=10))
    assert lease.heartbeats == 1


# --------------------------------------------------------------------- #
# 2. Unexpected exceptions land truthfully
# --------------------------------------------------------------------- #


def test_unexpected_exception_never_leaves_the_job_planned_and_replayable(
    conn, vault_dir, crypto_backend, encryptor, monkeypatch
):
    """Requirement 2: a job whose runner blew up before any portal
    contact must not be left at PLANNED, which reconciliation returns
    straight to QUEUED for a full replay."""
    seed_mcma_oujda_session(conn, vault_dir, crypto_backend)
    job_id = _execute_job_planned(conn, encryptor, typed_input=MODE_NORMAL_TYPED_INPUT, key="boom-1")

    def _explode(*args, **kwargs):
        raise RuntimeError("plan rebuild blew up")

    monkeypatch.setattr("mcma.execution.runner._rebuild_plan", _explode)

    outcomes = run_async(
        process_queued_planned_execute_jobs(
            conn, browser=object(), cfg=_cfg(vault_dir, crypto_backend), encryptor=encryptor
        )
    )
    assert outcomes == ("RUNNER_ERROR_RuntimeError",)
    row = AutomationJobsRepository(conn).get(job_id)
    assert row["status"] == "ERROR"
    assert row["reason_code"] == "RUNNER_EXCEPTION_RuntimeError"


def test_identity_failure_leaves_no_lease_and_no_registration(
    conn, vault_dir, crypto_backend, encryptor, monkeypatch
):
    """Requirement 6: every failure path closes the owned context and
    releases the lease -- never a leaked browser or lease."""
    seed_mcma_oujda_session(conn, vault_dir, crypto_backend)
    registry = ActiveReviewRegistry()
    cfg = _cfg(vault_dir, crypto_backend, registry)
    job_id = _execute_job_planned(conn, encryptor, typed_input=MODE_NORMAL_TYPED_INPUT, key="idfail-1")

    async def _failing_open(*args, **kwargs):
        raise RuntimeError("identity mismatch at the portal")

    monkeypatch.setattr("mcma.execution.runner.open_verified_writer", _failing_open)

    assert _run_execute(conn, job_id, cfg, encryptor) == "IDENTITY_FAILED"
    assert _lease_row(conn, MCMA_OUJDA_ACCOUNT_ID) is None
    assert registry.active_job_count() == 0
    assert registry.active_job_for_account(MCMA_OUJDA_ACCOUNT_ID) is None


def test_write_abort_closes_the_writer_and_releases_the_lease(
    conn, vault_dir, crypto_backend, encryptor, monkeypatch
):
    seed_mcma_oujda_session(conn, vault_dir, crypto_backend)
    registry = ActiveReviewRegistry()
    cfg = _cfg(vault_dir, crypto_backend, registry)
    job_id = _execute_job_planned(conn, encryptor, typed_input=MODE_NORMAL_TYPED_INPUT, key="wabort-1")

    def _fail_write(name, writer):
        if name == "fill_form_fields":
            raise RuntimeError("field write uncertain")

    writer = FakeWriter(on_call=_fail_write)
    _install_fake_writer(monkeypatch, writer)

    assert _run_execute(conn, job_id, cfg, encryptor) == "WRITE_ABORTED"
    assert writer.is_closed is True
    assert _lease_row(conn, MCMA_OUJDA_ACCOUNT_ID) is None
    assert registry.active_job_count() == 0
