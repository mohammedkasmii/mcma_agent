"""Correction batch (owner amendment, section E) -- the selected
account_id is recorded in BOTH the job row and audit data, atomically
with job creation."""

from mcma.execution.jobs import enqueue_dry_run
from jobs_test_support import ACCOUNT_ID, USER_ID, WORKFLOW, input_hash_for, typed_input_bytes


def test_dry_run_creation_writes_an_audit_event_with_the_selected_account(conn, encryptor):
    payload = {"dossier": "audit-1"}
    job_id = enqueue_dry_run(
        conn, account_id=ACCOUNT_ID, requested_by_user_id=USER_ID, workflow_name=WORKFLOW,
        input_hash=input_hash_for(payload), typed_input_bytes=typed_input_bytes(payload),
        idempotency_key="audit-1", encryptor=encryptor,
    )
    audit_row = conn.execute(
        "SELECT * FROM audit_events WHERE job_id = ? AND action = 'JOB_CREATED'", (job_id,)
    ).fetchone()
    assert audit_row is not None
    assert audit_row["account_id"] == ACCOUNT_ID
    assert audit_row["actor_user_id"] == USER_ID


def test_idempotent_resubmit_does_not_write_a_second_audit_event(conn, encryptor):
    payload = {"dossier": "audit-2"}
    kwargs = dict(
        conn=conn, account_id=ACCOUNT_ID, requested_by_user_id=USER_ID, workflow_name=WORKFLOW,
        input_hash=input_hash_for(payload), typed_input_bytes=typed_input_bytes(payload),
        idempotency_key="audit-2", encryptor=encryptor,
    )
    job_id_first = enqueue_dry_run(**kwargs)
    job_id_second = enqueue_dry_run(**kwargs)
    assert job_id_first == job_id_second
    count = conn.execute(
        "SELECT COUNT(*) AS c FROM audit_events WHERE job_id = ? AND action = 'JOB_CREATED'", (job_id_first,)
    ).fetchone()["c"]
    assert count == 1
