"""Migration 0007 -- workstation job dispatch lifecycle (Phase 1C-B).
Applied to a database already populated under 0001-0006 (not just an empty
one), proving the forward migration applies cleanly and that the extended
table's constraints/indexes hold the new guarantees: CLAIMED and RUNNING
are both active (at most one per job, at most one per runner), RELEASED/
EXPIRED/SUCCEEDED/FAILED are terminal with a fixed, mandatory outcome_code,
and every existing 0006-era row survives untouched. Synthetic data only."""

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
def pre_0007_conn(tmp_path, monkeypatch):
    """A database migrated through 0006 only, holding a user, an MCMA
    account, a runner, two dispatchable jobs, and one pre-existing 0006-era
    CLAIMED assignment -- everything the 0007 rebuild must carry forward
    untouched."""
    pre_dir = tmp_path / "migrations_pre_0007"
    pre_dir.mkdir()
    for path in db_module._MIGRATIONS_DIR.glob("*.sql"):
        if path.name < "0007":
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
    for job_id, created_at in ((JOB, "2026-01-01T00:00:00+00:00"), (JOB_2, "2026-01-01T00:01:00+00:00")):
        conn.execute(
            "INSERT INTO automation_jobs (job_id, account_id, requested_by_user_id, workflow_name, mode, status, "
            "input_hash, idempotency_key, created_at, state_version) "
            "VALUES (?, ?, ?, 'mission_normal', 'DRY_RUN', 'QUEUED', 'hash', ?, ?, 1)",
            (job_id, ACCOUNT, USER, job_id, created_at),
        )
    conn.execute(
        "INSERT INTO workstation_job_dispatch (assignment_id, job_id, runner_id, generation, claim_token_digest, "
        "status, claimed_at, lease_expires_at) VALUES ('pre-existing', ?, ?, 1, ?, 'CLAIMED', "
        "'2026-01-01T00:00:00+00:00', '2026-01-01T00:02:00+00:00')",
        (JOB, RUNNER, "a" * 64),
    )

    monkeypatch.undo()  # the real migrations dir again, so run_migrations now applies 0007
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


def test_migration_applies_forward_on_top_of_0006(pre_0007_conn):
    assert "0007_workstation_job_dispatch_lifecycle" in run_migrations(pre_0007_conn)


def test_new_table_has_the_expected_columns(pre_0007_conn):
    run_migrations(pre_0007_conn)
    columns = {row["name"] for row in pre_0007_conn.execute("PRAGMA table_info(workstation_job_dispatch)")}
    assert columns == {
        "assignment_id", "job_id", "runner_id", "generation", "claim_token_digest", "status",
        "claimed_at", "lease_expires_at", "last_renewed_at", "started_at", "finished_at", "outcome_code",
    }


def test_the_pre_existing_0006_era_claimed_row_survives_untouched(pre_0007_conn):
    run_migrations(pre_0007_conn)
    row = pre_0007_conn.execute(
        "SELECT * FROM workstation_job_dispatch WHERE assignment_id = 'pre-existing'"
    ).fetchone()
    assert row["job_id"] == JOB
    assert row["runner_id"] == RUNNER
    assert row["status"] == "CLAIMED"
    assert row["claim_token_digest"] == "a" * 64
    assert row["started_at"] is None


def test_running_is_now_a_valid_status(pre_0007_conn):
    run_migrations(pre_0007_conn)
    conn = pre_0007_conn
    conn.execute("UPDATE workstation_job_dispatch SET status = 'RUNNING', started_at = claimed_at "
                 "WHERE assignment_id = 'pre-existing'")
    row = conn.execute("SELECT status FROM workstation_job_dispatch WHERE assignment_id = 'pre-existing'").fetchone()
    assert row["status"] == "RUNNING"


def test_running_and_claimed_are_both_active_for_the_per_job_uniqueness(pre_0007_conn):
    run_migrations(pre_0007_conn)
    conn = pre_0007_conn
    conn.execute("UPDATE workstation_job_dispatch SET status = 'RUNNING', started_at = claimed_at "
                 "WHERE assignment_id = 'pre-existing'")
    with pytest.raises(sqlite3.IntegrityError):
        _claim_row(conn, assignment_id="a2", job_id=JOB, claim_token_digest="c" * 64)


def test_running_and_claimed_are_both_active_for_the_per_runner_uniqueness(pre_0007_conn):
    run_migrations(pre_0007_conn)
    conn = pre_0007_conn
    conn.execute("UPDATE workstation_job_dispatch SET status = 'RUNNING', started_at = claimed_at "
                 "WHERE assignment_id = 'pre-existing'")
    with pytest.raises(sqlite3.IntegrityError):
        _claim_row(conn, assignment_id="a2", job_id=JOB_2, runner_id=RUNNER, claim_token_digest="c" * 64)


def test_a_released_row_frees_the_job_and_runner_for_a_new_active_assignment(pre_0007_conn):
    run_migrations(pre_0007_conn)
    conn = pre_0007_conn
    conn.execute("UPDATE workstation_job_dispatch SET status = 'RELEASED', outcome_code = 'RUNNER_SHUTDOWN', "
                 "finished_at = '2026-01-01T00:01:00+00:00' WHERE assignment_id = 'pre-existing'")
    _claim_row(conn, assignment_id="a2", job_id=JOB, runner_id=RUNNER, generation=2, claim_token_digest="c" * 64)
    row = conn.execute("SELECT status FROM workstation_job_dispatch WHERE assignment_id = 'a2'").fetchone()
    assert row["status"] == "CLAIMED"


@pytest.mark.parametrize("status,started_at_from_claimed", [
    ("CLAIMED", True),   # CLAIMED must never carry a started_at
    ("RUNNING", False),  # RUNNING must always carry one
])
def test_started_at_presence_matches_status(pre_0007_conn, status, started_at_from_claimed):
    run_migrations(pre_0007_conn)
    started_at = "2026-01-01T00:00:00+00:00" if started_at_from_claimed else None
    with pytest.raises(sqlite3.IntegrityError):
        _claim_row(pre_0007_conn, status=status, started_at=started_at)


@pytest.mark.parametrize("status,outcome_code,started_at,finished_at", [
    ("CLAIMED", "RUNNER_SHUTDOWN", None, None),                                     # CLAIMED: no outcome_code
    ("RUNNING", "IDENTITY_MATCHED", "2026-01-01T00:00:00+00:00", None),             # RUNNING: no outcome_code
    ("SUCCEEDED", None, "2026-01-01T00:00:00+00:00", "2026-01-01T00:05:00+00:00"),  # SUCCEEDED: outcome mandatory
    ("SUCCEEDED", "IDENTITY_NOT_MATCHED", "2026-01-01T00:00:00+00:00", "2026-01-01T00:05:00+00:00"),  # wrong set
    ("FAILED", "IDENTITY_MATCHED", "2026-01-01T00:00:00+00:00", "2026-01-01T00:05:00+00:00"),         # wrong set
    ("RELEASED", "IDENTITY_MATCHED", None, "2026-01-01T00:05:00+00:00"),            # RELEASED: wrong set
    ("EXPIRED", "IDENTITY_MATCHED", None, "2026-01-01T00:05:00+00:00"),             # EXPIRED: must be LEASE_EXPIRED
])
def test_status_and_outcome_code_must_be_consistent(pre_0007_conn, status, outcome_code, started_at, finished_at):
    run_migrations(pre_0007_conn)
    with pytest.raises(sqlite3.IntegrityError):
        _claim_row(pre_0007_conn, status=status, outcome_code=outcome_code, started_at=started_at, finished_at=finished_at)


def test_succeeded_with_identity_matched_is_accepted(pre_0007_conn):
    run_migrations(pre_0007_conn)
    _claim_row(
        pre_0007_conn, status="SUCCEEDED", outcome_code="IDENTITY_MATCHED",
        started_at="2026-01-01T00:00:00+00:00", finished_at="2026-01-01T00:05:00+00:00",
    )


def test_succeeded_with_needs_review_no_browser_is_accepted(pre_0007_conn):
    run_migrations(pre_0007_conn)
    _claim_row(
        pre_0007_conn, status="SUCCEEDED", outcome_code="NEEDS_REVIEW_NO_BROWSER",
        started_at=None, finished_at="2026-01-01T00:05:00+00:00",
    )


@pytest.mark.parametrize("outcome_code", [
    "IDENTITY_NOT_MATCHED", "SESSION_UNAVAILABLE", "PORTAL_READ_FAILED", "RUNNER_CANCELLED", "PLANNING_FAILED",
])
def test_failed_accepts_each_of_its_own_outcome_codes(pre_0007_conn, outcome_code):
    run_migrations(pre_0007_conn)
    _claim_row(
        pre_0007_conn, status="FAILED", outcome_code=outcome_code,
        started_at="2026-01-01T00:00:00+00:00", finished_at="2026-01-01T00:05:00+00:00",
    )


def test_failed_with_planning_failed_never_requires_a_started_at(pre_0007_conn):
    """Dispatch correction (issue 3): a plan-build failure happens BEFORE
    the assignment ever reaches RUNNING -- the CLAIMED row it lands on
    FAILED never had a started_at, unlike a FAILED outcome reached via
    finish_job (which always ran through RUNNING first). The started_at
    presence CHECK constrains only CLAIMED/RUNNING, so FAILED with a NULL
    started_at must be accepted."""
    run_migrations(pre_0007_conn)
    _claim_row(
        pre_0007_conn, status="FAILED", outcome_code="PLANNING_FAILED",
        started_at=None, finished_at="2026-01-01T00:05:00+00:00",
    )


def test_finished_rows_are_retained_not_deleted(pre_0007_conn):
    run_migrations(pre_0007_conn)
    conn = pre_0007_conn
    conn.execute("UPDATE workstation_job_dispatch SET status = 'EXPIRED', outcome_code = 'LEASE_EXPIRED', "
                 "finished_at = '2026-01-01T00:05:00+00:00' WHERE assignment_id = 'pre-existing'")
    assert conn.execute("SELECT COUNT(*) AS n FROM workstation_job_dispatch").fetchone()["n"] == 1


def test_expected_indexes_exist(pre_0007_conn):
    run_migrations(pre_0007_conn)
    names = {row["name"] for row in pre_0007_conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'workstation_job_dispatch'"
    )}
    assert {
        "uq_workstation_job_dispatch_active_job",
        "uq_workstation_job_dispatch_active_runner",
        "idx_workstation_job_dispatch_job",
        "idx_workstation_job_dispatch_runner",
        "idx_workstation_job_dispatch_lease_expiry",
    } <= names


def test_foreign_keys_remain_intact_after_the_rebuild(pre_0007_conn):
    run_migrations(pre_0007_conn)
    assert pre_0007_conn.execute("PRAGMA foreign_key_check").fetchall() == []
