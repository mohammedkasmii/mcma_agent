"""Correction batch (owner amendment) -- the human browser handoff state
machine: READY_FOR_HUMAN_REVIEW is no longer terminal; browser closure
before vs. after it takes two different paths; only an explicit employee
action (confirm_review_completed / report_review_problem) can ever mark
a job HUMAN_CONFIRMED_COMPLETE; closure alone never means success."""

import pytest

from mcma.execution.jobs import (
    JobAuthorizationError,
    TERMINAL_STATUSES,
    confirm_review_completed,
    enqueue_dry_run,
    enqueue_execute,
    report_review_problem,
    run_dry_run_identity_check,
    run_dry_run_planning,
    run_execute_planning,
    run_execute_write,
    transition,
    transition_on_browser_closed,
)
from mcma.persistence.repositories.jobs import AutomationJobsRepository
from jobs_test_support import ACCOUNT_ID, USER_ID, WORKFLOW, input_hash_for, make_stub_plan, typed_input_bytes


def _make_ready_for_review_job(conn, encryptor, key="ready-1"):
    payload = {"dossier": key}
    dry_run_id = enqueue_dry_run(
        conn, account_id=ACCOUNT_ID, requested_by_user_id=USER_ID, workflow_name=WORKFLOW,
        input_hash=input_hash_for(payload), typed_input_bytes=typed_input_bytes(payload),
        idempotency_key=f"{key}-dry", encryptor=encryptor,
    )
    plan = make_stub_plan(input_hash_for(payload))
    run_dry_run_planning(conn, dry_run_id, build_plan=lambda: plan)
    run_dry_run_identity_check(conn, dry_run_id, check_identity_read_only=lambda: True)
    execute_id = enqueue_execute(
        conn, account_id=ACCOUNT_ID, requested_by_user_id=USER_ID, workflow_name=WORKFLOW,
        input_hash=input_hash_for(payload), typed_input_bytes=typed_input_bytes(payload),
        idempotency_key=f"{key}-exec", encryptor=encryptor, parent_job_id=dry_run_id,
    )
    run_execute_planning(conn, execute_id, rebuild_plan_from_retained_input=lambda: plan)
    status = run_execute_write(
        conn, execute_id,
        acquire_lease_and_verify_identity=lambda: object(),
        perform_writes_and_verify=lambda writer: True,
    )
    assert status == "READY_FOR_HUMAN_REVIEW"
    return execute_id


def test_ready_for_human_review_is_no_longer_terminal():
    assert "READY_FOR_HUMAN_REVIEW" not in TERMINAL_STATUSES


def test_awaiting_human_confirmation_and_human_confirmed_complete_are_terminal():
    assert "AWAITING_HUMAN_CONFIRMATION" in TERMINAL_STATUSES
    assert "HUMAN_CONFIRMED_COMPLETE" in TERMINAL_STATUSES


def test_ready_for_human_review_does_not_set_finished_at(conn, encryptor):
    job_id = _make_ready_for_review_job(conn, encryptor)
    row = AutomationJobsRepository(conn).get(job_id)
    assert row["finished_at"] is None


def test_browser_close_before_ready_interrupts_and_releases_lease(conn, encryptor):
    payload = {"dossier": "pre-ready"}
    dry_run_id = enqueue_dry_run(
        conn, account_id=ACCOUNT_ID, requested_by_user_id=USER_ID, workflow_name=WORKFLOW,
        input_hash=input_hash_for(payload), typed_input_bytes=typed_input_bytes(payload),
        idempotency_key="pre-ready-dry", encryptor=encryptor,
    )
    plan = make_stub_plan(input_hash_for(payload))
    run_dry_run_planning(conn, dry_run_id, build_plan=lambda: plan)
    run_dry_run_identity_check(conn, dry_run_id, check_identity_read_only=lambda: True)
    execute_id = enqueue_execute(
        conn, account_id=ACCOUNT_ID, requested_by_user_id=USER_ID, workflow_name=WORKFLOW,
        input_hash=input_hash_for(payload), typed_input_bytes=typed_input_bytes(payload),
        idempotency_key="pre-ready-exec", encryptor=encryptor, parent_job_id=dry_run_id,
    )
    run_execute_planning(conn, execute_id, rebuild_plan_from_retained_input=lambda: plan)
    transition(conn, execute_id, "ACQUIRING_ACCOUNT_LOCK")
    transition(conn, execute_id, "IDENTITY_VERIFYING")
    transition(conn, execute_id, "IDENTITY_VERIFIED")
    transition(conn, execute_id, "WRITING")

    release_calls = []
    result = transition_on_browser_closed(conn, execute_id, release_lease=lambda: release_calls.append(1))
    assert result == "INTERRUPTED_NEEDS_HUMAN_REVIEW"
    assert release_calls == [1]
    row = AutomationJobsRepository(conn).get(execute_id)
    assert row["status"] == "INTERRUPTED_NEEDS_HUMAN_REVIEW"
    assert row["finished_at"] is not None


def test_browser_close_after_ready_moves_to_awaiting_confirmation_never_success(conn, encryptor):
    job_id = _make_ready_for_review_job(conn, encryptor, key="post-ready-1")
    release_calls = []
    result = transition_on_browser_closed(conn, job_id, release_lease=lambda: release_calls.append(1))
    assert result == "AWAITING_HUMAN_CONFIRMATION"
    # Lease deliberately NOT released here -- still held until the human
    # explicitly confirms/reports a problem, so no second job can
    # concurrently use the same shared portal account mid-review.
    assert release_calls == []
    row = AutomationJobsRepository(conn).get(job_id)
    assert row["status"] == "AWAITING_HUMAN_CONFIRMATION"
    assert row["status"] != "HUMAN_CONFIRMED_COMPLETE"  # closure alone never means success


def test_browser_close_on_a_job_with_no_active_session_is_rejected(conn, encryptor):
    payload = {"dossier": "queued-only"}
    job_id = enqueue_dry_run(
        conn, account_id=ACCOUNT_ID, requested_by_user_id=USER_ID, workflow_name=WORKFLOW,
        input_hash=input_hash_for(payload), typed_input_bytes=typed_input_bytes(payload),
        idempotency_key="no-session", encryptor=encryptor,
    )
    with pytest.raises(JobAuthorizationError) as exc_info:
        transition_on_browser_closed(conn, job_id)
    assert exc_info.value.reason_code == "NO_ACTIVE_BROWSER_SESSION_FOR_JOB"


def test_confirm_review_completed_requires_awaiting_confirmation(conn, encryptor):
    job_id = _make_ready_for_review_job(conn, encryptor, key="confirm-1")
    with pytest.raises(JobAuthorizationError) as exc_info:
        confirm_review_completed(conn, job_id, confirmed_by_user_id=USER_ID)
    assert exc_info.value.reason_code == "REVIEW_NOT_AWAITING_CONFIRMATION"


def test_confirm_review_completed_succeeds_records_audit_and_releases_lease(conn, encryptor):
    job_id = _make_ready_for_review_job(conn, encryptor, key="confirm-2")
    transition_on_browser_closed(conn, job_id)  # -> AWAITING_HUMAN_CONFIRMATION

    release_calls = []
    result = confirm_review_completed(conn, job_id, confirmed_by_user_id=USER_ID, release_lease=lambda: release_calls.append(1))
    assert result == "HUMAN_CONFIRMED_COMPLETE"
    assert release_calls == [1]

    row = AutomationJobsRepository(conn).get(job_id)
    assert row["status"] == "HUMAN_CONFIRMED_COMPLETE"
    assert row["finished_at"] is not None

    audit_row = conn.execute(
        "SELECT * FROM audit_events WHERE job_id = ? AND action = 'HUMAN_CONFIRMED_COMPLETE'", (job_id,)
    ).fetchone()
    assert audit_row is not None
    assert audit_row["actor_user_id"] == USER_ID


def test_confirm_review_completed_is_idempotent_on_retry(conn, encryptor):
    job_id = _make_ready_for_review_job(conn, encryptor, key="confirm-3")
    transition_on_browser_closed(conn, job_id)
    first = confirm_review_completed(conn, job_id, confirmed_by_user_id=USER_ID)
    second = confirm_review_completed(conn, job_id, confirmed_by_user_id=USER_ID)
    assert first == second == "HUMAN_CONFIRMED_COMPLETE"
    audit_count = conn.execute(
        "SELECT COUNT(*) AS c FROM audit_events WHERE job_id = ? AND action = 'HUMAN_CONFIRMED_COMPLETE'", (job_id,)
    ).fetchone()["c"]
    assert audit_count == 1  # the idempotent retry did not write a second audit row


def test_wrong_status_confirmation_fails_truthfully_not_silently(conn, encryptor):
    payload = {"dossier": "wrong-status"}
    job_id = enqueue_dry_run(
        conn, account_id=ACCOUNT_ID, requested_by_user_id=USER_ID, workflow_name=WORKFLOW,
        input_hash=input_hash_for(payload), typed_input_bytes=typed_input_bytes(payload),
        idempotency_key="wrong-status", encryptor=encryptor,
    )
    with pytest.raises(JobAuthorizationError):
        confirm_review_completed(conn, job_id, confirmed_by_user_id=USER_ID)
    assert AutomationJobsRepository(conn).get(job_id)["status"] == "QUEUED"


def test_report_review_problem_from_ready_for_review(conn, encryptor):
    job_id = _make_ready_for_review_job(conn, encryptor, key="problem-1")
    release_calls = []
    result = report_review_problem(
        conn, job_id, reported_by_user_id=USER_ID, reason_code="EMPLOYEE_FOUND_DISCREPANCY",
        release_lease=lambda: release_calls.append(1),
    )
    assert result == "INTERRUPTED_NEEDS_HUMAN_REVIEW"
    assert release_calls == [1]
    row = AutomationJobsRepository(conn).get(job_id)
    assert row["status"] == "INTERRUPTED_NEEDS_HUMAN_REVIEW"
    assert row["reason_code"] == "EMPLOYEE_FOUND_DISCREPANCY"


def test_report_review_problem_from_awaiting_confirmation(conn, encryptor):
    job_id = _make_ready_for_review_job(conn, encryptor, key="problem-2")
    transition_on_browser_closed(conn, job_id)
    result = report_review_problem(conn, job_id, reported_by_user_id=USER_ID, reason_code="EMPLOYEE_DID_NOT_VALIDATE")
    assert result == "INTERRUPTED_NEEDS_HUMAN_REVIEW"


def test_report_review_problem_rejected_outside_human_handoff(conn, encryptor):
    payload = {"dossier": "not-in-handoff"}
    job_id = enqueue_dry_run(
        conn, account_id=ACCOUNT_ID, requested_by_user_id=USER_ID, workflow_name=WORKFLOW,
        input_hash=input_hash_for(payload), typed_input_bytes=typed_input_bytes(payload),
        idempotency_key="not-in-handoff", encryptor=encryptor,
    )
    with pytest.raises(JobAuthorizationError) as exc_info:
        report_review_problem(conn, job_id, reported_by_user_id=USER_ID, reason_code="X")
    assert exc_info.value.reason_code == "NOT_IN_HUMAN_HANDOFF"


def test_report_review_problem_never_marks_the_job_completed(conn, encryptor):
    job_id = _make_ready_for_review_job(conn, encryptor, key="problem-3")
    report_review_problem(conn, job_id, reported_by_user_id=USER_ID, reason_code="X")
    row = AutomationJobsRepository(conn).get(job_id)
    assert row["status"] != "HUMAN_CONFIRMED_COMPLETE"
