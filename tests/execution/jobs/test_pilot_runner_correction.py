"""Verification tests for the pilot-runner correction: state-before-I/O
ordering (run_execute_write_async), and the restart-safe fenced lease
release fallback (release_lease_if_owned_by_job / confirm_review_completed
/ report_review_problem without an in-memory handle)."""

import asyncio

import pytest

from mcma.execution.jobs import (
    JobAuthorizationError,
    confirm_review_completed,
    enqueue_dry_run,
    enqueue_execute,
    report_review_problem,
    run_dry_run_identity_check,
    run_dry_run_planning,
    run_execute_planning,
    run_execute_write_async,
)
from mcma.persistence.leases import acquire_lease, release_lease_if_owned_by_job
from mcma.persistence.repositories.jobs import AutomationJobsRepository
from jobs_test_support import ACCOUNT_ID, USER_ID, WORKFLOW, input_hash_for, make_stub_plan, typed_input_bytes


def _make_verified_dry_run(conn, encryptor, payload, key):
    job_id = enqueue_dry_run(
        conn, account_id=ACCOUNT_ID, requested_by_user_id=USER_ID, workflow_name=WORKFLOW,
        input_hash=input_hash_for(payload), typed_input_bytes=typed_input_bytes(payload),
        idempotency_key=key, encryptor=encryptor,
    )
    plan = make_stub_plan(input_hash_for(payload))
    run_dry_run_planning(conn, job_id, build_plan=lambda: plan)
    run_dry_run_identity_check(conn, job_id, check_identity_read_only=lambda: True)
    return job_id, plan


def _make_planned_execute(conn, encryptor, payload, key):
    dry_run_id, plan = _make_verified_dry_run(conn, encryptor, payload, key + "-dry")
    execute_id = enqueue_execute(
        conn, account_id=ACCOUNT_ID, requested_by_user_id=USER_ID, workflow_name=WORKFLOW,
        input_hash=input_hash_for(payload), typed_input_bytes=typed_input_bytes(payload),
        idempotency_key=key, encryptor=encryptor, parent_job_id=dry_run_id,
    )
    run_execute_planning(conn, execute_id, rebuild_plan_from_retained_input=lambda: plan)
    return execute_id


def test_async_success_reaches_ready_for_human_review(conn, encryptor):
    execute_id = _make_planned_execute(conn, encryptor, {"dossier": "async-1"}, "async-exec-1")

    async def _acquire():
        return "stub-writer"

    async def _perform(writer):
        return True

    outcome = asyncio.run(
        run_execute_write_async(
            conn, execute_id,
            acquire_lease_and_verify_identity=_acquire,
            perform_writes_and_verify=_perform,
        )
    )
    assert outcome == "READY_FOR_HUMAN_REVIEW"
    row = AutomationJobsRepository(conn).get(execute_id)
    assert row["status"] == "READY_FOR_HUMAN_REVIEW"


def test_async_transitions_commit_before_the_callable_runs(conn, encryptor):
    """The core bug fix: the DB must already show IDENTITY_VERIFYING (not
    PLANNED) by the time the 'browser I/O' callable is invoked, and WRITING
    (not IDENTITY_VERIFIED) by the time the write callable is invoked --
    proving state is durable BEFORE the I/O, not caught up after it."""
    execute_id = _make_planned_execute(conn, encryptor, {"dossier": "async-2"}, "async-exec-2")
    observed = {}

    async def _acquire():
        observed["status_during_acquire"] = AutomationJobsRepository(conn).get(execute_id)["status"]
        return "stub-writer"

    async def _perform(writer):
        observed["status_during_write"] = AutomationJobsRepository(conn).get(execute_id)["status"]
        return True

    asyncio.run(
        run_execute_write_async(
            conn, execute_id,
            acquire_lease_and_verify_identity=_acquire,
            perform_writes_and_verify=_perform,
        )
    )
    assert observed["status_during_acquire"] == "IDENTITY_VERIFYING"
    assert observed["status_during_write"] == "WRITING"


def test_async_identity_failure_stops_before_writing(conn, encryptor):
    execute_id = _make_planned_execute(conn, encryptor, {"dossier": "async-3"}, "async-exec-3")
    write_attempted = {"called": False}

    async def _fail_identity():
        raise RuntimeError("identity mismatch")

    async def _perform(writer):
        write_attempted["called"] = True
        return True

    outcome = asyncio.run(
        run_execute_write_async(
            conn, execute_id,
            acquire_lease_and_verify_identity=_fail_identity,
            perform_writes_and_verify=_perform,
        )
    )
    assert outcome == "IDENTITY_FAILED"
    assert write_attempted["called"] is False


def test_async_write_failure_reaches_write_aborted(conn, encryptor):
    execute_id = _make_planned_execute(conn, encryptor, {"dossier": "async-4"}, "async-exec-4")

    async def _acquire():
        return "stub-writer"

    async def _perform(writer):
        return False

    outcome = asyncio.run(
        run_execute_write_async(
            conn, execute_id,
            acquire_lease_and_verify_identity=_acquire,
            perform_writes_and_verify=_perform,
        )
    )
    assert outcome == "WRITE_ABORTED"


def test_release_lease_if_owned_by_job_deletes_only_the_owning_job(conn):
    acquire_lease(conn, ACCOUNT_ID, "instance-1", owner_job_id="job-A", ttl_seconds=60)
    # A different job trying to release does nothing.
    assert release_lease_if_owned_by_job(conn, ACCOUNT_ID, "job-B") is False
    row = conn.execute("SELECT owner_job_id FROM account_leases WHERE account_id=?", (ACCOUNT_ID,)).fetchone()
    assert row["owner_job_id"] == "job-A"
    # The owning job releases it successfully.
    assert release_lease_if_owned_by_job(conn, ACCOUNT_ID, "job-A") is True
    row = conn.execute("SELECT owner_job_id FROM account_leases WHERE account_id=?", (ACCOUNT_ID,)).fetchone()
    assert row is None
    # Idempotent -- nothing left to release.
    assert release_lease_if_owned_by_job(conn, ACCOUNT_ID, "job-A") is False


def _make_awaiting_confirmation_execute(conn, encryptor, payload, key):
    execute_id = _make_planned_execute(conn, encryptor, payload, key)

    async def _acquire():
        return "stub-writer"

    async def _perform(writer):
        return True

    asyncio.run(
        run_execute_write_async(
            conn, execute_id,
            acquire_lease_and_verify_identity=_acquire,
            perform_writes_and_verify=_perform,
        )
    )
    from mcma.execution.jobs import transition
    transition(conn, execute_id, "AWAITING_HUMAN_CONFIRMATION", expected_from_statuses=frozenset({"READY_FOR_HUMAN_REVIEW"}))
    return execute_id


def test_confirm_review_completed_falls_back_to_fenced_release_without_a_handle(conn, encryptor):
    """Simulates the restart scenario: no in-memory AccountLeaseHandle
    exists (release_lease=None), but the account_leases row this job
    itself acquired during EXECUTE is still sitting there -- confirm must
    still clean it up via the fenced fallback."""
    execute_id = _make_awaiting_confirmation_execute(conn, encryptor, {"dossier": "async-5"}, "async-exec-5")
    acquire_lease(conn, ACCOUNT_ID, "instance-restarted", owner_job_id=execute_id, ttl_seconds=999)

    status = confirm_review_completed(conn, execute_id, confirmed_by_user_id=USER_ID)
    assert status == "HUMAN_CONFIRMED_COMPLETE"
    row = conn.execute("SELECT * FROM account_leases WHERE account_id=?", (ACCOUNT_ID,)).fetchone()
    assert row is None


def test_confirm_review_completed_fallback_never_touches_a_newer_jobs_lease(conn, encryptor):
    """Fencing check: if some OTHER job has since legitimately acquired
    the account lease, an old job's belated confirm must never delete it."""
    execute_id = _make_awaiting_confirmation_execute(conn, encryptor, {"dossier": "async-6"}, "async-exec-6")
    acquire_lease(conn, ACCOUNT_ID, "instance-other", owner_job_id="some-other-newer-job", ttl_seconds=999)

    confirm_review_completed(conn, execute_id, confirmed_by_user_id=USER_ID)
    row = conn.execute("SELECT owner_job_id FROM account_leases WHERE account_id=?", (ACCOUNT_ID,)).fetchone()
    assert row is not None
    assert row["owner_job_id"] == "some-other-newer-job"


def test_report_review_problem_falls_back_to_fenced_release_without_a_handle(conn, encryptor):
    execute_id = _make_awaiting_confirmation_execute(conn, encryptor, {"dossier": "async-7"}, "async-exec-7")
    acquire_lease(conn, ACCOUNT_ID, "instance-restarted", owner_job_id=execute_id, ttl_seconds=999)

    status = report_review_problem(conn, execute_id, reported_by_user_id=USER_ID, reason_code="TEST")
    assert status == "INTERRUPTED_NEEDS_HUMAN_REVIEW"
    row = conn.execute("SELECT * FROM account_leases WHERE account_id=?", (ACCOUNT_ID,)).fetchone()
    assert row is None
