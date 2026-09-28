"""Migration 0008 -- workstation job dispatch EXECUTE outcomes (Phase
1C-C, Pass 1). Applied to a database already populated under 0001-0007
(not just an empty one), proving the forward migration applies cleanly
and that the extended table's outcome_code CHECK constraints hold the new
EXECUTE-only guarantees, while every pre-existing 0007-era row and
DRY_RUN-only outcome_code still behaves exactly as before. Synthetic data
only."""

import shutil
import sqlite3

import pytest

import mcma.persistence.db as db_module
from mcma.persistence.db import connect, run_migrations

ACCOUNT = "acct-mcma-oujda"
USER = "user-1"
ENROLLMENT = "enrollment-1"
RUNNER = "runner-1"
JOB = "job-1"
JOB_2 = "job-2"


@pytest.fixture()
def pre_0008_conn(tmp_path, monkeypatch):
    """A database migrated through 0007 only, holding a user, an MCMA
    account, a runner, two dispatchable jobs, and one pre-existing 0007-era
    RUNNING assignment -- everything the 0008 rebuild must carry forward
    untouched."""
    pre_dir = tmp_path / "migrations_pre_0008"
    pre_dir.mkdir()
    for path in db_module._MIGRATIONS_DIR.glob("*.sql"):
        if path.name < "0008":
            shutil.copy(path, pre_dir / path.name)
    monkeypatch.setattr(db_module, "_MIGRATIONS_DIR", pre_dir)

    conn = connect(tmp_path / "mcma_test.sqlite3")
    run_migrations(conn)
    conn.execute(
        "INSERT INTO users (user_id, username, password_hash, role, active) VALUES (?, ?, 'hash', 'admin', 1)",
        (USER, "user-1-username"),
    )
    conn.execute(
        "INSERT INTO accounts (account_id, label, entity, scope, active, created_at) "
        "VALUES (?, 'MCMA Oujda', 'MCMA', 'OUJDA', 1, '2026-01-01T00:00:00+00:00')",
        (ACCOUNT,),
    )
    conn.execute(
        "INSERT INTO runner_enrollments (enrollment_id, code_digest, target_user_id, created_by_user_id, "
        "created_at, expires_at, consumed_at) VALUES (?, ?, ?, ?, '2026-01-01T00:00:00+00:00', "
        "'2026-01-02T00:00:00+00:00', '2026-01-01T00:00:00+00:00')",
        (ENROLLMENT, "0" * 64, USER, USER),
    )
    conn.execute(
        "INSERT INTO runners (runner_id, user_id, credential_digest, runner_label, status, enrollment_id, created_at) "
        "VALUES (?, ?, ?, 'Test Runner', 'ACTIVE', ?, '2026-01-01T00:00:00+00:00')",
        (RUNNER, USER, "1" * 64, ENROLLMENT),
    )
    for job_id, mode, status, created_at in (
        (JOB, "EXECUTE", "PLANNED", "2026-01-01T00:00:00+00:00"),
        (JOB_2, "DRY_RUN", "QUEUED", "2026-01-01T00:01:00+00:00"),
    ):
        conn.execute(
            "INSERT INTO automation_jobs (job_id, account_id, requested_by_user_id, workflow_name, mode, status, "
            "input_hash, idempotency_key, created_at, state_version) "
            "VALUES (?, ?, ?, 'mission_normal', ?, ?, 'hash', ?, ?, 1)",
            (job_id, ACCOUNT, USER, mode, status, job_id, created_at),
        )
    conn.execute(
        "INSERT INTO workstation_job_dispatch (assignment_id, job_id, runner_id, generation, claim_token_digest, "
        "status, claimed_at, lease_expires_at, started_at) VALUES ('pre-existing', ?, ?, 1, ?, 'RUNNING', "
        "'2026-01-01T00:00:00+00:00', '2026-01-01T00:02:00+00:00', '2026-01-01T00:00:00+00:00')",
        (JOB, RUNNER, "a" * 64),
    )

    monkeypatch.undo()  # the real migrations dir again, so run_migrations now applies 0008
    yield conn
    conn.close()


def _claim_row(
    conn, *, assignment_id="assignment-1", job_id=JOB_2, runner_id=RUNNER, generation=1,
    claim_token_digest="b" * 64, status="CLAIMED", claimed_at="2026-01-01T00:00:00+00:00",
    lease_expires_at="2026-01-01T01:00:00+00:00", **extra,
):
    columns = {
        "assignment_id": assignment_id, "job_id": job_id, "runner_id": runner_id, "generation": generation,
        "claim_token_digest": claim_token_digest, "status": status, "claimed_at": claimed_at,
        "lease_expires_at": lease_expires_at,
    }
    columns.update(extra)
    names = ", ".join(columns)
    placeholders = ", ".join("?" for _ in columns)
    conn.execute(f"INSERT INTO workstation_job_dispatch ({names}) VALUES ({placeholders})", tuple(columns.values()))


def test_migration_applies_forward_on_top_of_0007(pre_0008_conn):
    assert "0008_workstation_job_dispatch_execute_outcomes" in run_migrations(pre_0008_conn)


def test_columns_are_unchanged(pre_0008_conn):
    run_migrations(pre_0008_conn)
    columns = {row["name"] for row in pre_0008_conn.execute("PRAGMA table_info(workstation_job_dispatch)")}
    assert columns == {
        "assignment_id", "job_id", "runner_id", "generation", "claim_token_digest", "status",
        "claimed_at", "lease_expires_at", "last_renewed_at", "started_at", "finished_at", "outcome_code",
    }


def test_the_pre_existing_0007_era_running_row_survives_untouched(pre_0008_conn):
    run_migrations(pre_0008_conn)
    row = pre_0008_conn.execute(
        "SELECT * FROM workstation_job_dispatch WHERE assignment_id = 'pre-existing'"
    ).fetchone()
    assert row["job_id"] == JOB
    assert row["runner_id"] == RUNNER
    assert row["status"] == "RUNNING"
    assert row["claim_token_digest"] == "a" * 64
    assert row["started_at"] is not None


@pytest.mark.parametrize("outcome_code", [
    "IDENTITY_MATCHED", "NEEDS_REVIEW_NO_BROWSER", "READY_FOR_HUMAN_REVIEW",
])
def test_succeeded_accepts_each_of_its_own_outcome_codes(pre_0008_conn, outcome_code):
    run_migrations(pre_0008_conn)
    _claim_row(
        pre_0008_conn, status="SUCCEEDED", outcome_code=outcome_code,
        started_at="2026-01-01T00:00:00+00:00", finished_at="2026-01-01T00:05:00+00:00",
    )


@pytest.mark.parametrize("outcome_code", [
    "IDENTITY_NOT_MATCHED", "SESSION_UNAVAILABLE", "PORTAL_READ_FAILED", "RUNNER_CANCELLED", "PLANNING_FAILED",
    "IDENTITY_FAILED", "WRITE_ABORTED", "SESSION_NOT_READY", "INPUT_OR_PLAN_MISMATCH", "INTERNAL_EXECUTION_ERROR",
    "LEASE_LOST",
])
def test_failed_accepts_each_of_its_own_outcome_codes_including_execute(pre_0008_conn, outcome_code):
    run_migrations(pre_0008_conn)
    _claim_row(
        pre_0008_conn, status="FAILED", outcome_code=outcome_code,
        started_at="2026-01-01T00:00:00+00:00", finished_at="2026-01-01T00:05:00+00:00",
    )


@pytest.mark.parametrize("status,outcome_code", [
    ("SUCCEEDED", "IDENTITY_FAILED"),          # a FAILED-only outcome on SUCCEEDED
    ("SUCCEEDED", "WRITE_ABORTED"),
    ("FAILED", "READY_FOR_HUMAN_REVIEW"),      # a SUCCEEDED-only outcome on FAILED
    ("CLAIMED", "READY_FOR_HUMAN_REVIEW"),     # active statuses never carry an outcome_code
    ("RUNNING", "WRITE_ABORTED"),
])
def test_execute_outcomes_stay_bound_to_the_correct_terminal_status(pre_0008_conn, status, outcome_code):
    run_migrations(pre_0008_conn)
    started_at = "2026-01-01T00:00:00+00:00" if status != "CLAIMED" else None
    finished_at = "2026-01-01T00:05:00+00:00" if status in ("SUCCEEDED", "FAILED") else None
    with pytest.raises(sqlite3.IntegrityError):
        _claim_row(pre_0008_conn, status=status, outcome_code=outcome_code, started_at=started_at, finished_at=finished_at)


def test_expired_still_requires_exactly_lease_expired(pre_0008_conn):
    run_migrations(pre_0008_conn)
    with pytest.raises(sqlite3.IntegrityError):
        _claim_row(
            pre_0008_conn, status="EXPIRED", outcome_code="INTERNAL_EXECUTION_ERROR",
            started_at=None, finished_at="2026-01-01T00:05:00+00:00",
        )
    _claim_row(
        pre_0008_conn, assignment_id="expired-ok", status="EXPIRED", outcome_code="LEASE_EXPIRED",
        started_at=None, finished_at="2026-01-01T00:05:00+00:00",
    )


def test_finished_rows_are_retained_not_deleted(pre_0008_conn):
    run_migrations(pre_0008_conn)
    conn = pre_0008_conn
    conn.execute("UPDATE workstation_job_dispatch SET status = 'SUCCEEDED', outcome_code = 'READY_FOR_HUMAN_REVIEW', "
                 "finished_at = '2026-01-01T00:05:00+00:00' WHERE assignment_id = 'pre-existing'")
    assert conn.execute("SELECT COUNT(*) AS n FROM workstation_job_dispatch").fetchone()["n"] == 1


def test_expected_indexes_exist(pre_0008_conn):
    run_migrations(pre_0008_conn)
    names = {row["name"] for row in pre_0008_conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'workstation_job_dispatch'"
    )}
    assert {
        "uq_workstation_job_dispatch_active_job",
        "uq_workstation_job_dispatch_active_runner",
        "idx_workstation_job_dispatch_job",
        "idx_workstation_job_dispatch_runner",
        "idx_workstation_job_dispatch_lease_expiry",
    } <= names


def test_foreign_keys_remain_intact_after_the_rebuild(pre_0008_conn):
    run_migrations(pre_0008_conn)
    assert pre_0008_conn.execute("PRAGMA foreign_key_check").fetchall() == []
