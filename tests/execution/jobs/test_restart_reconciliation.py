"""INC-12 -- deterministic restart reconciliation (WORKFLOW_STATE_MODEL.md
§7): every non-terminal status has an exact, tested outcome."""

from datetime import datetime, timedelta, timezone

import pytest

from mcma.execution.jobs import enqueue_dry_run, transition
from mcma.execution.reconcile import reconcile_on_restart
from mcma.persistence.leases import acquire_lease
from mcma.persistence.repositories.jobs import AutomationJobsRepository
from jobs_test_support import ACCOUNT_ID, USER_ID, WORKFLOW, input_hash_for, typed_input_bytes


def _enqueue_at(conn, encryptor, payload, status, key):
    job_id = enqueue_dry_run(
        conn, account_id=ACCOUNT_ID, requested_by_user_id=USER_ID, workflow_name=WORKFLOW,
        input_hash=input_hash_for(payload), typed_input_bytes=typed_input_bytes(payload),
        idempotency_key=key, encryptor=encryptor,
    )
    if status != "QUEUED":
        transition(conn, job_id, status)
    return job_id


@pytest.mark.parametrize("status", ["QUEUED", "PLANNING", "PLANNED", "READ_ONLY_IDENTITY_CHECK"])
def test_restart_read_capable_statuses_return_to_queued_and_replan(conn, encryptor, status):
    payload = {"dossier": status}
    job_id = _enqueue_at(conn, encryptor, payload, status, key=f"key-{status}")
    outcomes = reconcile_on_restart(conn, encryptor=encryptor)
    assert outcomes[job_id] == "QUEUED"
    assert AutomationJobsRepository(conn).get(job_id)["status"] == "QUEUED"


def test_restart_queued_planning_planned_replans_deterministically(conn, encryptor):
    payload = {"dossier": "m1"}
    job_id = _enqueue_at(conn, encryptor, payload, "PLANNING", key="m1")
    outcomes = reconcile_on_restart(conn, encryptor=encryptor)
    assert outcomes[job_id] == "QUEUED"


def test_restart_read_only_identity_check_returns_to_queued(conn, encryptor):
    payload = {"dossier": "m2"}
    job_id = _enqueue_at(conn, encryptor, payload, "READ_ONLY_IDENTITY_CHECK", key="m2")
    outcomes = reconcile_on_restart(conn, encryptor=encryptor)
    assert outcomes[job_id] == "QUEUED"


@pytest.mark.parametrize("status", ["ACQUIRING_ACCOUNT_LOCK", "IDENTITY_VERIFYING", "IDENTITY_VERIFIED"])
def test_restart_pre_write_statuses_abort_and_release_lease(conn, encryptor, status):
    payload = {"dossier": status}
    job_id = _enqueue_at(conn, encryptor, payload, status, key=f"prewrite-{status}")
    acquire_lease(conn, ACCOUNT_ID, "instance-1")
    outcomes = reconcile_on_restart(conn, encryptor=encryptor)
    assert outcomes[job_id] == "ABORTED_ON_RESTART"
    assert AutomationJobsRepository(conn).get(job_id)["status"] == "ABORTED_ON_RESTART"
    assert conn.execute("SELECT COUNT(*) AS c FROM account_leases WHERE account_id=?", (ACCOUNT_ID,)).fetchone()["c"] == 0


def test_restart_acquiring_lock_identity_verifying_aborts_on_restart_and_releases_lease(conn, encryptor):
    payload = {"dossier": "m3"}
    job_id = _enqueue_at(conn, encryptor, payload, "IDENTITY_VERIFYING", key="m3")
    acquire_lease(conn, ACCOUNT_ID, "instance-1")
    outcomes = reconcile_on_restart(conn, encryptor=encryptor)
    assert outcomes[job_id] == "ABORTED_ON_RESTART"


def test_restart_identity_verified_aborts_on_restart_and_releases_lease(conn, encryptor):
    payload = {"dossier": "m4"}
    job_id = _enqueue_at(conn, encryptor, payload, "IDENTITY_VERIFIED", key="m4")
    acquire_lease(conn, ACCOUNT_ID, "instance-1")
    outcomes = reconcile_on_restart(conn, encryptor=encryptor)
    assert outcomes[job_id] == "ABORTED_ON_RESTART"
    assert conn.execute("SELECT COUNT(*) AS c FROM account_leases").fetchone()["c"] == 0


@pytest.mark.parametrize("status", ["WRITING", "VERIFYING"])
def test_restart_writing_verifying_never_auto_resumed(conn, encryptor, status):
    payload = {"dossier": status}
    job_id = _enqueue_at(conn, encryptor, payload, status, key=f"interrupted-{status}")
    acquire_lease(conn, ACCOUNT_ID, "instance-1")
    outcomes = reconcile_on_restart(conn, encryptor=encryptor)
    assert outcomes[job_id] == "INTERRUPTED_NEEDS_HUMAN_REVIEW"
    assert conn.execute("SELECT COUNT(*) AS c FROM account_leases").fetchone()["c"] == 0


def test_restart_missing_input_errors_missing_job_input(conn, encryptor):
    payload = {"dossier": "m5"}
    job_id = _enqueue_at(conn, encryptor, payload, "PLANNED", key="m5")
    conn.execute("DELETE FROM job_inputs WHERE job_id = ?", (job_id,))
    outcomes = reconcile_on_restart(conn, encryptor=encryptor)
    assert outcomes[job_id] == "ERROR"
    row = AutomationJobsRepository(conn).get(job_id)
    assert row["status"] == "ERROR"
    assert row["reason_code"] == "MISSING_JOB_INPUT"


def test_restart_expired_input_errors_input_expired(conn, encryptor):
    payload = {"dossier": "m6"}
    job_id = _enqueue_at(conn, encryptor, payload, "PLANNED", key="m6")
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    conn.execute("UPDATE job_inputs SET expires_at = ? WHERE job_id = ?", (past, job_id))
    outcomes = reconcile_on_restart(conn, encryptor=encryptor)
    assert outcomes[job_id] == "ERROR"
    assert AutomationJobsRepository(conn).get(job_id)["reason_code"] == "INPUT_EXPIRED"


def test_restart_undecryptable_input_errors_input_undecryptable(conn, encryptor):
    class _AlwaysFailsDecrypt:
        def encrypt(self, plaintext):
            return plaintext

        def decrypt(self, ciphertext):
            raise RuntimeError("cannot decrypt")

    payload = {"dossier": "m7"}
    job_id = _enqueue_at(conn, encryptor, payload, "PLANNED", key="m7")
    outcomes = reconcile_on_restart(conn, encryptor=_AlwaysFailsDecrypt())
    assert outcomes[job_id] == "ERROR"
    assert AutomationJobsRepository(conn).get(job_id)["reason_code"] == "INPUT_UNDECRYPTABLE"


def test_restart_hash_mismatch_errors_input_hash_mismatch(conn, encryptor):
    payload = {"dossier": "m8"}
    job_id = _enqueue_at(conn, encryptor, payload, "PLANNED", key="m8")
    tampered = encryptor.encrypt(b'{"dossier": "TAMPERED"}')
    conn.execute("UPDATE job_inputs SET ciphertext = ? WHERE job_id = ?", (tampered, job_id))
    outcomes = reconcile_on_restart(conn, encryptor=encryptor)
    assert outcomes[job_id] == "ERROR"
    assert AutomationJobsRepository(conn).get(job_id)["reason_code"] == "INPUT_HASH_MISMATCH"


def test_restart_releases_stale_leases_first(conn, encryptor):
    payload = {"dossier": "m9"}
    job_id = _enqueue_at(conn, encryptor, payload, "PLANNED", key="m9")
    acquire_lease(conn, ACCOUNT_ID, "instance-1", ttl_seconds=1)
    past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    conn.execute("UPDATE account_leases SET expires_at = ?", (past,))
    reconcile_on_restart(conn, encryptor=encryptor)
    assert conn.execute("SELECT COUNT(*) AS c FROM account_leases").fetchone()["c"] == 0


@pytest.mark.parametrize(
    "status",
    ["DRY_RUN_VERIFIED", "NEEDS_REVIEW", "IDENTITY_FAILED", "WRITE_ABORTED", "READY_FOR_HUMAN_REVIEW", "ERROR"],
)
def test_restart_terminal_statuses_are_kept_unchanged(conn, encryptor, status):
    payload = {"dossier": status}
    job_id = _enqueue_at(conn, encryptor, payload, status, key=f"terminal-{status}")
    outcomes = reconcile_on_restart(conn, encryptor=encryptor)
    assert job_id not in outcomes  # never touched -- already terminal, excluded by list_non_terminal()
    assert AutomationJobsRepository(conn).get(job_id)["status"] == status
