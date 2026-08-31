"""INC-15 Fable-review corrections -- closing the authorization gaps
found in execution/jobs.py: run_execute_write must not be callable
without having gone through run_execute_planning first, and a DRY_RUN
transition must not be reachable on an EXECUTE-mode job (which would let
that EXECUTE job become a valid "parent" for another EXECUTE job)."""

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
        conn, account_id=ACCOUNT_ID, requested_by_user_id=USER_ID, workflow_name=WORKFLOW,
        input_hash=input_hash_for(payload), typed_input_bytes=typed_input_bytes(payload),
        idempotency_key=key, encryptor=encryptor,
    )
    plan = make_stub_plan(input_hash_for(payload))
    run_dry_run_planning(conn, job_id, build_plan=lambda: plan)
    run_dry_run_identity_check(conn, job_id, check_identity_read_only=lambda: True)
    return job_id, plan


def test_run_execute_write_rejects_a_job_that_skipped_planning(conn, encryptor):
    payload = {"dossier": "gap-1"}
    dry_run_id, plan = _make_verified_dry_run(conn, encryptor, payload)
    execute_id = enqueue_execute(
        conn, account_id=ACCOUNT_ID, requested_by_user_id=USER_ID, workflow_name=WORKFLOW,
        input_hash=input_hash_for(payload), typed_input_bytes=typed_input_bytes(payload),
        idempotency_key="gap-exec-1", encryptor=encryptor, parent_job_id=dry_run_id,
    )
    # run_execute_planning was never called -- the job is still QUEUED.
    with pytest.raises(JobAuthorizationError) as exc_info:
        run_execute_write(
            conn, execute_id,
            acquire_lease_and_verify_identity=lambda: "writer",
            perform_writes_and_verify=lambda w: True,
        )
    assert exc_info.value.reason_code == "EXECUTE_WRITE_REQUIRES_PLANNED_STATUS"

    # Positive control: the SAME job, planned first, now succeeds.
    run_execute_planning(conn, execute_id, rebuild_plan_from_retained_input=lambda: plan)
    outcome = run_execute_write(
        conn, execute_id,
        acquire_lease_and_verify_identity=lambda: "writer",
        perform_writes_and_verify=lambda w: True,
    )
    assert outcome == "READY_FOR_HUMAN_REVIEW"


def test_execute_mode_job_cannot_be_driven_through_the_dry_run_path(conn, encryptor):
    payload = {"dossier": "gap-2"}
    dry_run_id, plan = _make_verified_dry_run(conn, encryptor, payload)
    execute_id = enqueue_execute(
        conn, account_id=ACCOUNT_ID, requested_by_user_id=USER_ID, workflow_name=WORKFLOW,
        input_hash=input_hash_for(payload), typed_input_bytes=typed_input_bytes(payload),
        idempotency_key="gap-exec-2", encryptor=encryptor, parent_job_id=dry_run_id,
    )
    with pytest.raises(JobAuthorizationError) as exc_info:
        run_dry_run_planning(conn, execute_id, build_plan=lambda: plan)
    assert exc_info.value.reason_code == "WRONG_JOB_MODE_EXPECTED_DRY_RUN"


def test_an_execute_job_can_never_serve_as_another_executes_parent(conn, encryptor):
    """Even if somehow driven to DRY_RUN_VERIFIED-shaped state, an
    EXECUTE-mode job must be rejected as a parent (mode is checked at the
    parent-authorization boundary too, defense in depth)."""
    payload = {"dossier": "gap-3"}
    dry_run_id, plan = _make_verified_dry_run(conn, encryptor, payload)
    execute_id = enqueue_execute(
        conn, account_id=ACCOUNT_ID, requested_by_user_id=USER_ID, workflow_name=WORKFLOW,
        input_hash=input_hash_for(payload), typed_input_bytes=typed_input_bytes(payload),
        idempotency_key="gap-exec-3", encryptor=encryptor, parent_job_id=dry_run_id,
    )
    # Force the row directly to simulate a hypothetical bypass (the
    # normal API can't reach this state at all after the fix above).
    from mcma.execution.jobs import transition

    transition(conn, execute_id, "PLANNED")
    transition(conn, execute_id, "READ_ONLY_IDENTITY_CHECK")
    transition(conn, execute_id, "DRY_RUN_VERIFIED")

    grandchild_id = enqueue_execute(
        conn, account_id=ACCOUNT_ID, requested_by_user_id=USER_ID, workflow_name=WORKFLOW,
        input_hash=input_hash_for(payload), typed_input_bytes=typed_input_bytes(payload),
        idempotency_key="gap-exec-4", encryptor=encryptor, parent_job_id=execute_id,
    )
    with pytest.raises(JobAuthorizationError) as exc_info:
        run_execute_planning(conn, grandchild_id, rebuild_plan_from_retained_input=lambda: plan)
    assert exc_info.value.reason_code == "PARENT_NOT_DRY_RUN_VERIFIED"
