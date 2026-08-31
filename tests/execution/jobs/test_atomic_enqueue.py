"""INC-12 -- atomic enqueue and idempotency."""

import pytest

from mcma.execution.jobs import enqueue_dry_run
from jobs_test_support import ACCOUNT_ID, USER_ID, WORKFLOW, input_hash_for, typed_input_bytes


class _FailingEncryptor:
    def encrypt(self, plaintext: bytes) -> bytes:
        raise RuntimeError("simulated encryption failure")

    def decrypt(self, ciphertext: bytes) -> bytes:
        return ciphertext


def test_atomic_enqueue_all_or_nothing(conn):
    payload = {"dossier": "x"}
    with pytest.raises(RuntimeError):
        enqueue_dry_run(
            conn,
            account_id=ACCOUNT_ID,
            requested_by_user_id=USER_ID,
            workflow_name=WORKFLOW,
            input_hash=input_hash_for(payload),
            typed_input_bytes=typed_input_bytes(payload),
            idempotency_key="key-1",
            encryptor=_FailingEncryptor(),
        )
    # Nothing committed: no job row, no version bump, no outbox event.
    assert conn.execute("SELECT COUNT(*) AS c FROM automation_jobs").fetchone()["c"] == 0
    assert conn.execute("SELECT COUNT(*) AS c FROM job_inputs").fetchone()["c"] == 0
    assert conn.execute("SELECT COUNT(*) AS c FROM event_outbox").fetchone()["c"] == 0
    assert conn.execute("SELECT COUNT(*) AS c FROM account_state_version").fetchone()["c"] == 0


def test_idempotent_resubmit_returns_existing_job(conn, encryptor):
    payload = {"dossier": "x"}
    job_id_1 = enqueue_dry_run(
        conn,
        account_id=ACCOUNT_ID,
        requested_by_user_id=USER_ID,
        workflow_name=WORKFLOW,
        input_hash=input_hash_for(payload),
        typed_input_bytes=typed_input_bytes(payload),
        idempotency_key="key-1",
        encryptor=encryptor,
    )
    job_id_2 = enqueue_dry_run(
        conn,
        account_id=ACCOUNT_ID,
        requested_by_user_id=USER_ID,
        workflow_name=WORKFLOW,
        input_hash=input_hash_for(payload),
        typed_input_bytes=typed_input_bytes(payload),
        idempotency_key="key-1",
        encryptor=encryptor,
    )
    assert job_id_1 == job_id_2
    assert conn.execute("SELECT COUNT(*) AS c FROM automation_jobs").fetchone()["c"] == 1


def test_enqueue_creates_job_input_and_outbox_event_in_one_transaction(conn, encryptor):
    payload = {"dossier": "y"}
    job_id = enqueue_dry_run(
        conn,
        account_id=ACCOUNT_ID,
        requested_by_user_id=USER_ID,
        workflow_name=WORKFLOW,
        input_hash=input_hash_for(payload),
        typed_input_bytes=typed_input_bytes(payload),
        idempotency_key="key-2",
        encryptor=encryptor,
    )
    assert conn.execute("SELECT status FROM automation_jobs WHERE job_id=?", (job_id,)).fetchone()["status"] == "QUEUED"
    assert conn.execute("SELECT job_id FROM job_inputs WHERE job_id=?", (job_id,)).fetchone() is not None
    assert conn.execute("SELECT version FROM account_state_version WHERE account_id=?", (ACCOUNT_ID,)).fetchone()["version"] == 1
    events = conn.execute("SELECT type FROM event_outbox WHERE account_id=?", (ACCOUNT_ID,)).fetchall()
    assert [e["type"] for e in events] == ["JOB_CREATED"]
