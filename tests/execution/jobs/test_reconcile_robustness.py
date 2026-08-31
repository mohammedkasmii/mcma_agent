"""INC-15 Fable-review correction -- a single corrupted job row must not
abort restart reconciliation for every other job."""

from mcma.execution.jobs import enqueue_dry_run
from mcma.execution.reconcile import reconcile_on_restart
from mcma.persistence.repositories.jobs import AutomationJobsRepository
from jobs_test_support import ACCOUNT_ID, USER_ID, WORKFLOW, input_hash_for, typed_input_bytes


def test_one_corrupted_row_does_not_block_reconciliation_of_other_jobs(conn, encryptor):
    healthy_id = enqueue_dry_run(
        conn, account_id=ACCOUNT_ID, requested_by_user_id=USER_ID, workflow_name=WORKFLOW,
        input_hash=input_hash_for({"dossier": "healthy"}), typed_input_bytes=typed_input_bytes({"dossier": "healthy"}),
        idempotency_key="healthy-1", encryptor=encryptor,
    )
    corrupted_id = enqueue_dry_run(
        conn, account_id=ACCOUNT_ID, requested_by_user_id=USER_ID, workflow_name=WORKFLOW,
        input_hash=input_hash_for({"dossier": "corrupted"}), typed_input_bytes=typed_input_bytes({"dossier": "corrupted"}),
        idempotency_key="corrupted-1", encryptor=encryptor,
    )
    # Corrupt the retained input's expires_at so datetime.fromisoformat()
    # raises a bare ValueError -- not a JobInputUnavailable subclass.
    conn.execute("UPDATE job_inputs SET expires_at = 'not-a-real-timestamp' WHERE job_id = ?", (corrupted_id,))

    outcomes = reconcile_on_restart(conn, encryptor=encryptor)

    assert outcomes[healthy_id] == "QUEUED"  # unaffected by the corrupted sibling
    assert outcomes[corrupted_id] == "ERROR"
    row = AutomationJobsRepository(conn).get(corrupted_id)
    assert row["status"] == "ERROR"
    assert row["reason_code"].startswith("RECONCILE_UNEXPECTED_")
