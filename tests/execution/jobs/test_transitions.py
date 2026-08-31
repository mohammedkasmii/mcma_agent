"""INC-12 -- every transition writes its outbox event in the same
transaction as the status change."""

from mcma.execution.jobs import enqueue_dry_run, transition
from jobs_test_support import ACCOUNT_ID, USER_ID, WORKFLOW, input_hash_for, typed_input_bytes


def test_every_transition_writes_outbox_in_same_transaction(conn, encryptor):
    payload = {"dossier": "n"}
    job_id = enqueue_dry_run(
        conn, account_id=ACCOUNT_ID, requested_by_user_id=USER_ID, workflow_name=WORKFLOW,
        input_hash=input_hash_for(payload), typed_input_bytes=typed_input_bytes(payload),
        idempotency_key="trans-1", encryptor=encryptor,
    )
    version_before = conn.execute(
        "SELECT version FROM account_state_version WHERE account_id=?", (ACCOUNT_ID,)
    ).fetchone()["version"]
    events_before = conn.execute("SELECT COUNT(*) AS c FROM event_outbox").fetchone()["c"]

    transition(conn, job_id, "PLANNING")

    version_after = conn.execute(
        "SELECT version FROM account_state_version WHERE account_id=?", (ACCOUNT_ID,)
    ).fetchone()["version"]
    events_after = conn.execute("SELECT COUNT(*) AS c FROM event_outbox").fetchone()["c"]
    job_row = conn.execute("SELECT status, state_version FROM automation_jobs WHERE job_id=?", (job_id,)).fetchone()

    assert version_after == version_before + 1
    assert events_after == events_before + 1
    assert job_row["status"] == "PLANNING"
    assert job_row["state_version"] == version_after


def test_transition_to_unknown_status_is_rejected_by_the_schema(conn, encryptor):
    import sqlite3

    import pytest

    payload = {"dossier": "o"}
    job_id = enqueue_dry_run(
        conn, account_id=ACCOUNT_ID, requested_by_user_id=USER_ID, workflow_name=WORKFLOW,
        input_hash=input_hash_for(payload), typed_input_bytes=typed_input_bytes(payload),
        idempotency_key="trans-2", encryptor=encryptor,
    )
    with pytest.raises(sqlite3.IntegrityError):
        transition(conn, job_id, "NOT_A_REAL_STATUS")
    # The failed transition rolled back -- status and outbox unaffected.
    assert conn.execute("SELECT status FROM automation_jobs WHERE job_id=?", (job_id,)).fetchone()["status"] == "QUEUED"
