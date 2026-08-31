"""INC-12 -- EXECUTE authorization, hash re-check, and the full write
lifecycle (ACQUIRING_ACCOUNT_LOCK -> ... -> READY_FOR_HUMAN_REVIEW /
WRITE_ABORTED / IDENTITY_FAILED)."""

import pytest

from mcma.execution.jobs import (
    JobAuthorizationError,
    enqueue_dry_run,
    enqueue_execute,
    run_dry_run_identity_check,
    run_dry_run_planning,
    run_execute_planning,
    run_execute_write,
)
from jobs_test_support import ACCOUNT_ID, USER_ID, WORKFLOW, input_hash_for, make_stub_plan, typed_input_bytes


def _make_verified_dry_run(conn, encryptor, payload, key="dry-1"):
    job_id = enqueue_dry_run(
        conn,
        account_id=ACCOUNT_ID,
        requested_by_user_id=USER_ID,
        workflow_name=WORKFLOW,
        input_hash=input_hash_for(payload),
        typed_input_bytes=typed_input_bytes(payload),
        idempotency_key=key,
        encryptor=encryptor,
    )
    plan = make_stub_plan(input_hash_for(payload))
    run_dry_run_planning(conn, job_id, build_plan=lambda: plan)
    run_dry_run_identity_check(conn, job_id, check_identity_read_only=lambda: True)
    return job_id, plan


def test_execute_requires_dry_run_verified_parent_same_account_workflow(conn, encryptor):
    payload = {"dossier": "e"}
    dry_run_id, plan = _make_verified_dry_run(conn, encryptor, payload)
    execute_id = enqueue_execute(
        conn,
        account_id=ACCOUNT_ID,
        requested_by_user_id=USER_ID,
        workflow_name=WORKFLOW,
        input_hash=input_hash_for(payload),
        typed_input_bytes=typed_input_bytes(payload),
        idempotency_key="exec-1",
        encryptor=encryptor,
        parent_job_id=dry_run_id,
    )
    run_execute_planning(conn, execute_id, rebuild_plan_from_retained_input=lambda: plan)
    assert conn.execute("SELECT status FROM automation_jobs WHERE job_id=?", (execute_id,)).fetchone()["status"] == "PLANNED"


def test_execute_rejects_parent_not_dry_run_verified(conn, encryptor):
    payload = {"dossier": "f"}
    job_id = enqueue_dry_run(
        conn, account_id=ACCOUNT_ID, requested_by_user_id=USER_ID, workflow_name=WORKFLOW,
        input_hash=input_hash_for(payload), typed_input_bytes=typed_input_bytes(payload),
        idempotency_key="dry-2", encryptor=encryptor,
    )  # left at QUEUED, never verified
    execute_id = enqueue_execute(
        conn, account_id=ACCOUNT_ID, requested_by_user_id=USER_ID, workflow_name=WORKFLOW,
        input_hash=input_hash_for(payload), typed_input_bytes=typed_input_bytes(payload),
        idempotency_key="exec-2", encryptor=encryptor, parent_job_id=job_id,
    )
    with pytest.raises(JobAuthorizationError) as exc_info:
        run_execute_planning(conn, execute_id, rebuild_plan_from_retained_input=lambda: make_stub_plan(input_hash_for(payload)))
    assert exc_info.value.reason_code == "PARENT_NOT_DRY_RUN_VERIFIED"


def test_execute_rejects_different_account_or_workflow_parent(conn, encryptor):
    conn.execute(
        "INSERT INTO accounts (account_id, label, entity, scope, active, created_at) "
        "VALUES ('acct-2', 'Other', 'MAMDA', 'NADOR', 1, '2026-01-01T00:00:00+00:00')"
    )
    payload = {"dossier": "g"}
    dry_run_id, _ = _make_verified_dry_run(conn, encryptor, payload)
    execute_id = enqueue_execute(
        conn, account_id="acct-2", requested_by_user_id=USER_ID, workflow_name=WORKFLOW,
        input_hash=input_hash_for(payload), typed_input_bytes=typed_input_bytes(payload),
        idempotency_key="exec-3", encryptor=encryptor, parent_job_id=dry_run_id,
    )
    with pytest.raises(JobAuthorizationError) as exc_info:
        run_execute_planning(conn, execute_id, rebuild_plan_from_retained_input=lambda: make_stub_plan(input_hash_for(payload)))
    assert exc_info.value.reason_code == "PARENT_ACCOUNT_OR_WORKFLOW_MISMATCH"


def test_execute_rechecks_input_hash_and_plan_hash(conn, encryptor):
    payload = {"dossier": "h"}
    dry_run_id, plan = _make_verified_dry_run(conn, encryptor, payload)
    execute_id = enqueue_execute(
        conn, account_id=ACCOUNT_ID, requested_by_user_id=USER_ID, workflow_name=WORKFLOW,
        input_hash=input_hash_for(payload), typed_input_bytes=typed_input_bytes(payload),
        idempotency_key="exec-4", encryptor=encryptor, parent_job_id=dry_run_id,
    )
    changed_plan = make_stub_plan(input_hash_for(payload), plan_hash="a-different-plan-hash")
    with pytest.raises(JobAuthorizationError) as exc_info:
        run_execute_planning(conn, execute_id, rebuild_plan_from_retained_input=lambda: changed_plan)
    assert exc_info.value.reason_code == "INPUT_CHANGED"
    row = conn.execute("SELECT status, reason_code FROM automation_jobs WHERE job_id=?", (execute_id,)).fetchone()
    assert row["status"] == "ERROR"
    assert row["reason_code"] == "INPUT_CHANGED"


def test_execute_write_success_reaches_ready_for_human_review(conn, encryptor):
    payload = {"dossier": "i"}
    dry_run_id, plan = _make_verified_dry_run(conn, encryptor, payload)
    execute_id = enqueue_execute(
        conn, account_id=ACCOUNT_ID, requested_by_user_id=USER_ID, workflow_name=WORKFLOW,
        input_hash=input_hash_for(payload), typed_input_bytes=typed_input_bytes(payload),
        idempotency_key="exec-5", encryptor=encryptor, parent_job_id=dry_run_id,
    )
    run_execute_planning(conn, execute_id, rebuild_plan_from_retained_input=lambda: plan)
    outcome = run_execute_write(
        conn, execute_id,
        acquire_lease_and_verify_identity=lambda: "stub-writer",
        perform_writes_and_verify=lambda writer: True,
    )
    assert outcome == "READY_FOR_HUMAN_REVIEW"
    assert conn.execute("SELECT status FROM automation_jobs WHERE job_id=?", (execute_id,)).fetchone()["status"] == "READY_FOR_HUMAN_REVIEW"


def test_execute_identity_failure_stops_before_writing(conn, encryptor):
    payload = {"dossier": "j"}
    dry_run_id, plan = _make_verified_dry_run(conn, encryptor, payload)
    execute_id = enqueue_execute(
        conn, account_id=ACCOUNT_ID, requested_by_user_id=USER_ID, workflow_name=WORKFLOW,
        input_hash=input_hash_for(payload), typed_input_bytes=typed_input_bytes(payload),
        idempotency_key="exec-6", encryptor=encryptor, parent_job_id=dry_run_id,
    )
    run_execute_planning(conn, execute_id, rebuild_plan_from_retained_input=lambda: plan)

    write_attempted = {"called": False}

    def _perform_writes(writer):
        write_attempted["called"] = True
        return True

    def _fail_identity():
        raise RuntimeError("identity mismatch")

    outcome = run_execute_write(
        conn, execute_id,
        acquire_lease_and_verify_identity=_fail_identity,
        perform_writes_and_verify=_perform_writes,
    )
    assert outcome == "IDENTITY_FAILED"
    assert write_attempted["called"] is False


def test_execute_write_failure_reaches_write_aborted(conn, encryptor):
    payload = {"dossier": "k"}
    dry_run_id, plan = _make_verified_dry_run(conn, encryptor, payload)
    execute_id = enqueue_execute(
        conn, account_id=ACCOUNT_ID, requested_by_user_id=USER_ID, workflow_name=WORKFLOW,
        input_hash=input_hash_for(payload), typed_input_bytes=typed_input_bytes(payload),
        idempotency_key="exec-7", encryptor=encryptor, parent_job_id=dry_run_id,
    )
    run_execute_planning(conn, execute_id, rebuild_plan_from_retained_input=lambda: plan)
    outcome = run_execute_write(
        conn, execute_id,
        acquire_lease_and_verify_identity=lambda: "stub-writer",
        perform_writes_and_verify=lambda writer: False,  # native calc / read-back mismatch
    )
    assert outcome == "WRITE_ABORTED"


def test_readiness_terminal_at_ready_for_human_review(conn, encryptor):
    """INV-5: the runner never transitions a job to a human-completed
    status; there is no status value or function in this module that
    could move a job past READY_FOR_HUMAN_REVIEW."""
    from mcma.persistence.repositories.jobs import AutomationJobsRepository

    payload = {"dossier": "l"}
    dry_run_id, plan = _make_verified_dry_run(conn, encryptor, payload)
    execute_id = enqueue_execute(
        conn, account_id=ACCOUNT_ID, requested_by_user_id=USER_ID, workflow_name=WORKFLOW,
        input_hash=input_hash_for(payload), typed_input_bytes=typed_input_bytes(payload),
        idempotency_key="exec-8", encryptor=encryptor, parent_job_id=dry_run_id,
    )
    run_execute_planning(conn, execute_id, rebuild_plan_from_retained_input=lambda: plan)
    run_execute_write(
        conn, execute_id,
        acquire_lease_and_verify_identity=lambda: "stub-writer",
        perform_writes_and_verify=lambda writer: True,
    )
    row = AutomationJobsRepository(conn).get(execute_id)
    assert row["status"] == "READY_FOR_HUMAN_REVIEW"
    assert "FINALIZED_BY_HUMAN" not in row["status"]
    # FINALIZED_BY_HUMAN is not even a legal value in the status CHECK.
    with pytest.raises(Exception):
        conn.execute("UPDATE automation_jobs SET status='FINALIZED_BY_HUMAN' WHERE job_id=?", (execute_id,))
