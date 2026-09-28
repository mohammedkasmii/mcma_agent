"""INC-12 -- every transition writes its outbox event in the same
transaction as the status change."""

import pytest

from mcma.execution.jobs import TransitionRequiresActiveTransaction, enqueue_dry_run, transition
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


# --------------------------------------------------------------------- #
# Transaction-helper hardening (Phase 1C-B release-blocker correction):
# transition(in_transaction=True) must fail closed -- never silently
# autocommit each statement as its own separate write -- when no
# transaction is actually active on the connection.
# --------------------------------------------------------------------- #


def test_in_transaction_true_without_an_active_transaction_fails_closed(conn, encryptor):
    payload = {"dossier": "p"}
    job_id = enqueue_dry_run(
        conn, account_id=ACCOUNT_ID, requested_by_user_id=USER_ID, workflow_name=WORKFLOW,
        input_hash=input_hash_for(payload), typed_input_bytes=typed_input_bytes(payload),
        idempotency_key="trans-3", encryptor=encryptor,
    )
    assert conn.in_transaction is False
    with pytest.raises(TransitionRequiresActiveTransaction):
        transition(conn, job_id, "PLANNING", in_transaction=True)
    # Never silently autocommitted -- the job is completely untouched.
    assert conn.execute("SELECT status FROM automation_jobs WHERE job_id=?", (job_id,)).fetchone()["status"] == "QUEUED"


def test_in_transaction_true_with_an_active_transaction_succeeds(conn, encryptor):
    payload = {"dossier": "q"}
    job_id = enqueue_dry_run(
        conn, account_id=ACCOUNT_ID, requested_by_user_id=USER_ID, workflow_name=WORKFLOW,
        input_hash=input_hash_for(payload), typed_input_bytes=typed_input_bytes(payload),
        idempotency_key="trans-4", encryptor=encryptor,
    )
    conn.execute("BEGIN IMMEDIATE")
    try:
        assert conn.in_transaction is True
        transition(conn, job_id, "PLANNING", in_transaction=True)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    assert conn.execute("SELECT status FROM automation_jobs WHERE job_id=?", (job_id,)).fetchone()["status"] == "PLANNING"


def test_transition_requires_active_transaction_is_never_a_public_autocommit_path(conn, encryptor):
    """There is no way to call transition(in_transaction=True) and have it
    quietly succeed without an active transaction -- the guard raises
    before any read/write of automation_jobs beyond the initial (harmless)
    existence lookup."""
    payload = {"dossier": "r"}
    job_id = enqueue_dry_run(
        conn, account_id=ACCOUNT_ID, requested_by_user_id=USER_ID, workflow_name=WORKFLOW,
        input_hash=input_hash_for(payload), typed_input_bytes=typed_input_bytes(payload),
        idempotency_key="trans-5", encryptor=encryptor,
    )
    events_before = conn.execute("SELECT COUNT(*) AS c FROM event_outbox").fetchone()["c"]
    with pytest.raises(TransitionRequiresActiveTransaction):
        transition(conn, job_id, "PLANNING", in_transaction=True)
    events_after = conn.execute("SELECT COUNT(*) AS c FROM event_outbox").fetchone()["c"]
    assert events_after == events_before
