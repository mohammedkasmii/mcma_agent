"""Correction batch (owner amendment) -- MAMDA read-only enforcement,
defense-in-depth layer 2 (mcma.execution). MAMDA supports notifications
only: no automation_jobs row of ANY kind may ever be created for a MAMDA
account, and an EXECUTE job cannot reach planning/writer construction if
its account is (or has become) MAMDA/inactive -- this module never trusts
that the API already checked this. MCMA is the positive control proving
the rejection is a real account-type check, not a universal block.
"""

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


def _seed_mamda_account(conn, account_id: str = "acct-mamda") -> str:
    conn.execute(
        "INSERT INTO accounts (account_id, label, entity, scope, active, created_at) "
        "VALUES (?, 'MAMDA test account', 'MAMDA', 'NADOR', 1, '2026-01-01T00:00:00+00:00')",
        (account_id,),
    )
    return account_id


def test_mamda_notification_reads_are_unaffected(conn):
    """This module never touches notifications/reads at all -- proving the
    absence of any coupling: seeding a MAMDA account and reading it back
    via plain SQL (what a notification poller would do) is unaffected."""
    account_id = _seed_mamda_account(conn)
    row = conn.execute("SELECT entity FROM accounts WHERE account_id = ?", (account_id,)).fetchone()
    assert row["entity"] == "MAMDA"


def test_dry_run_enqueue_rejected_for_mamda_account(conn, encryptor):
    account_id = _seed_mamda_account(conn)
    payload = {"dossier": "m"}
    with pytest.raises(JobAuthorizationError) as exc_info:
        enqueue_dry_run(
            conn,
            account_id=account_id,
            requested_by_user_id=USER_ID,
            workflow_name=WORKFLOW,
            input_hash=input_hash_for(payload),
            typed_input_bytes=typed_input_bytes(payload),
            idempotency_key="mamda-dry-1",
            encryptor=encryptor,
        )
    assert exc_info.value.reason_code == "MAMDA_ACCOUNT_NOT_WRITABLE"


def test_no_job_row_is_created_after_mamda_rejection(conn, encryptor):
    account_id = _seed_mamda_account(conn)
    payload = {"dossier": "m"}
    with pytest.raises(JobAuthorizationError):
        enqueue_dry_run(
            conn,
            account_id=account_id,
            requested_by_user_id=USER_ID,
            workflow_name=WORKFLOW,
            input_hash=input_hash_for(payload),
            typed_input_bytes=typed_input_bytes(payload),
            idempotency_key="mamda-dry-2",
            encryptor=encryptor,
        )
    count = conn.execute("SELECT COUNT(*) AS c FROM automation_jobs WHERE account_id = ?", (account_id,)).fetchone()["c"]
    assert count == 0
    inputs_count = conn.execute("SELECT COUNT(*) AS c FROM job_inputs").fetchone()["c"]
    assert inputs_count == 0
    outbox_count = conn.execute("SELECT COUNT(*) AS c FROM event_outbox").fetchone()["c"]
    assert outbox_count == 0


def test_execute_enqueue_rejected_for_mamda_account_even_with_a_forged_parent_id(conn, encryptor):
    account_id = _seed_mamda_account(conn)
    payload = {"dossier": "m"}
    with pytest.raises(JobAuthorizationError) as exc_info:
        enqueue_execute(
            conn,
            account_id=account_id,
            requested_by_user_id=USER_ID,
            workflow_name=WORKFLOW,
            input_hash=input_hash_for(payload),
            typed_input_bytes=typed_input_bytes(payload),
            idempotency_key="mamda-exec-1",
            encryptor=encryptor,
            parent_job_id="does-not-matter-rejected-before-parent-is-even-checked",
        )
    assert exc_info.value.reason_code == "MAMDA_ACCOUNT_NOT_WRITABLE"


def test_run_execute_planning_rejects_an_account_downgraded_to_mamda_after_enqueue(conn, encryptor):
    """Defense in depth: even if a job somehow already exists for what is
    NOW a MAMDA/inactive account (e.g. re-classified between enqueue and
    planning), run_execute_planning re-reads the account itself -- it
    never trusts the state at enqueue time."""
    payload = {"dossier": "m"}
    dry_run_id = enqueue_dry_run(
        conn, account_id=ACCOUNT_ID, requested_by_user_id=USER_ID, workflow_name=WORKFLOW,
        input_hash=input_hash_for(payload), typed_input_bytes=typed_input_bytes(payload),
        idempotency_key="downgrade-dry-1", encryptor=encryptor,
    )
    plan = make_stub_plan(input_hash_for(payload))
    run_dry_run_planning(conn, dry_run_id, build_plan=lambda: plan)
    run_dry_run_identity_check(conn, dry_run_id, check_identity_read_only=lambda: True)
    execute_id = enqueue_execute(
        conn, account_id=ACCOUNT_ID, requested_by_user_id=USER_ID, workflow_name=WORKFLOW,
        input_hash=input_hash_for(payload), typed_input_bytes=typed_input_bytes(payload),
        idempotency_key="downgrade-exec-1", encryptor=encryptor, parent_job_id=dry_run_id,
    )

    # The account is re-classified as MAMDA AFTER the EXECUTE job exists.
    conn.execute("UPDATE accounts SET entity = 'MAMDA' WHERE account_id = ?", (ACCOUNT_ID,))

    with pytest.raises(JobAuthorizationError) as exc_info:
        run_execute_planning(conn, execute_id, rebuild_plan_from_retained_input=lambda: plan)
    assert exc_info.value.reason_code == "MAMDA_ACCOUNT_NOT_WRITABLE"


def test_run_execute_write_never_constructs_a_writer_or_acquires_a_lease_for_mamda(conn, encryptor):
    payload = {"dossier": "m"}
    dry_run_id = enqueue_dry_run(
        conn, account_id=ACCOUNT_ID, requested_by_user_id=USER_ID, workflow_name=WORKFLOW,
        input_hash=input_hash_for(payload), typed_input_bytes=typed_input_bytes(payload),
        idempotency_key="downgrade-dry-2", encryptor=encryptor,
    )
    plan = make_stub_plan(input_hash_for(payload))
    run_dry_run_planning(conn, dry_run_id, build_plan=lambda: plan)
    run_dry_run_identity_check(conn, dry_run_id, check_identity_read_only=lambda: True)
    execute_id = enqueue_execute(
        conn, account_id=ACCOUNT_ID, requested_by_user_id=USER_ID, workflow_name=WORKFLOW,
        input_hash=input_hash_for(payload), typed_input_bytes=typed_input_bytes(payload),
        idempotency_key="downgrade-exec-2", encryptor=encryptor, parent_job_id=dry_run_id,
    )
    run_execute_planning(conn, execute_id, rebuild_plan_from_retained_input=lambda: plan)

    conn.execute("UPDATE accounts SET entity = 'MAMDA' WHERE account_id = ?", (ACCOUNT_ID,))

    lease_calls = []
    write_calls = []

    def acquire_lease_and_verify_identity():
        lease_calls.append(1)
        return object()

    def perform_writes_and_verify(writer):
        write_calls.append(1)
        return True

    with pytest.raises(JobAuthorizationError) as exc_info:
        run_execute_write(
            conn, execute_id,
            acquire_lease_and_verify_identity=acquire_lease_and_verify_identity,
            perform_writes_and_verify=perform_writes_and_verify,
        )
    assert exc_info.value.reason_code == "MAMDA_ACCOUNT_NOT_WRITABLE"
    assert lease_calls == []  # no lease acquisition was ever attempted
    assert write_calls == []  # no writer/browser-facing call was ever attempted


def test_mcma_reaches_the_next_safe_planning_gate_as_positive_control(conn, encryptor):
    """Proves the MAMDA rejection above is a real account-type check, not
    a universal block: the SAME sequence against the MCMA fixture account
    reaches PLANNED normally."""
    payload = {"dossier": "ok"}
    dry_run_id = enqueue_dry_run(
        conn, account_id=ACCOUNT_ID, requested_by_user_id=USER_ID, workflow_name=WORKFLOW,
        input_hash=input_hash_for(payload), typed_input_bytes=typed_input_bytes(payload),
        idempotency_key="mcma-dry-1", encryptor=encryptor,
    )
    plan = make_stub_plan(input_hash_for(payload))
    run_dry_run_planning(conn, dry_run_id, build_plan=lambda: plan)
    run_dry_run_identity_check(conn, dry_run_id, check_identity_read_only=lambda: True)
    execute_id = enqueue_execute(
        conn, account_id=ACCOUNT_ID, requested_by_user_id=USER_ID, workflow_name=WORKFLOW,
        input_hash=input_hash_for(payload), typed_input_bytes=typed_input_bytes(payload),
        idempotency_key="mcma-exec-1", encryptor=encryptor, parent_job_id=dry_run_id,
    )
    result_plan = run_execute_planning(conn, execute_id, rebuild_plan_from_retained_input=lambda: plan)
    assert result_plan is plan
