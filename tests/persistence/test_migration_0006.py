"""Migration 0006 -- workstation job dispatch. Applied to a database already
populated under 0001-0005 (not just an empty one), proving the forward
migration applies cleanly on top of the existing schema and that the new
table's constraints/indexes hold the guarantees Phase 1C-A depends on:
at most one active (CLAIMED) assignment per job, at most one per runner,
and finished rows are retained as history. Synthetic data only."""

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
def pre_0006_conn(tmp_path, monkeypatch):
    """A database migrated through 0005 only, holding a user, an MCMA
    account, a runner, and two dispatchable jobs -- everything
    workstation_job_dispatch's foreign keys and claim-selection queries
    touch, all seeded BEFORE 0006 exists."""
    pre_dir = tmp_path / "migrations_pre_0006"
    pre_dir.mkdir()
    for path in db_module._MIGRATIONS_DIR.glob("*.sql"):
        if path.name < "0006":
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
            "VALUES (?, ?, ?, 'RENOUVELLEMENT_CONTRAT', 'DRY_RUN', 'QUEUED', 'hash', ?, ?, 1)",
            (job_id, ACCOUNT, USER, job_id, created_at),
        )

    monkeypatch.undo()  # the real migrations dir again, so run_migrations now applies 0006
    yield conn
    conn.close()


def _claim_row(
    conn, *, assignment_id="assignment-1", job_id=JOB, runner_id=RUNNER, generation=1,
    claim_token_digest="a" * 64, status="CLAIMED", claimed_at="2026-01-01T00:00:00+00:00",
    lease_expires_at="2026-01-01T00:02:00+00:00", **extra,
):
    columns = {
        "assignment_id": assignment_id, "job_id": job_id, "runner_id": runner_id, "generation": generation,
        "claim_token_digest": claim_token_digest, "status": status, "claimed_at": claimed_at,
        "lease_expires_at": lease_expires_at,
    }
    columns.update(extra)
    names = ", ".join(columns)
    placeholders = ", ".join("?" for _ in columns)
    conn.execute(
        f"INSERT INTO workstation_job_dispatch ({names}) VALUES ({placeholders})",
        tuple(columns.values()),
    )


def test_migration_applies_forward_on_top_of_0005(pre_0006_conn):
    assert "0006_workstation_job_dispatch" in run_migrations(pre_0006_conn)


def test_new_table_has_the_expected_columns(pre_0006_conn):
    # A SUBSET check, not an exact match: run_migrations() applies every
    # migration still pending, not just 0006 -- 0007 (Phase 1C-B) later
    # extends this same table with its own additional column(s). This test
    # only proves 0006's OWN contribution is present, never that nothing
    # newer has been added since; see test_migration_0007.py for that
    # migration's own exact-column proof.
    run_migrations(pre_0006_conn)
    columns = {row["name"] for row in pre_0006_conn.execute("PRAGMA table_info(workstation_job_dispatch)")}
    assert {
        "assignment_id", "job_id", "runner_id", "generation", "claim_token_digest", "status",
        "claimed_at", "lease_expires_at", "last_renewed_at", "finished_at", "outcome_code",
    } <= columns


def test_automation_jobs_is_untouched(pre_0006_conn):
    before = {row["name"] for row in pre_0006_conn.execute("PRAGMA table_info(automation_jobs)")}
    run_migrations(pre_0006_conn)
    after = {row["name"] for row in pre_0006_conn.execute("PRAGMA table_info(automation_jobs)")}
    assert before == after


def test_a_second_active_assignment_for_the_same_job_is_rejected(pre_0006_conn):
    run_migrations(pre_0006_conn)
    conn = pre_0006_conn
    _claim_row(conn, assignment_id="a1", claim_token_digest="a" * 64)
    with pytest.raises(sqlite3.IntegrityError):
        _claim_row(conn, assignment_id="a2", claim_token_digest="b" * 64)


def test_a_second_active_assignment_for_the_same_runner_is_rejected(pre_0006_conn):
    run_migrations(pre_0006_conn)
    conn = pre_0006_conn
    _claim_row(conn, assignment_id="a1", job_id=JOB, claim_token_digest="a" * 64)
    with pytest.raises(sqlite3.IntegrityError):
        _claim_row(conn, assignment_id="a2", job_id=JOB_2, claim_token_digest="b" * 64)


def test_a_released_row_frees_the_job_and_runner_for_a_new_active_assignment(pre_0006_conn):
    run_migrations(pre_0006_conn)
    conn = pre_0006_conn
    _claim_row(conn, assignment_id="a1", claim_token_digest="a" * 64)
    conn.execute(
        "UPDATE workstation_job_dispatch SET status = 'RELEASED', outcome_code = 'RUNNER_SHUTDOWN', "
        "finished_at = '2026-01-01T00:01:00+00:00' WHERE assignment_id = 'a1'"
    )
    _claim_row(conn, assignment_id="a2", generation=2, claim_token_digest="b" * 64)
    rows = conn.execute("SELECT assignment_id, status FROM workstation_job_dispatch ORDER BY assignment_id").fetchall()
    assert [(r["assignment_id"], r["status"]) for r in rows] == [("a1", "RELEASED"), ("a2", "CLAIMED")]


def test_finished_rows_are_retained_not_deleted(pre_0006_conn):
    run_migrations(pre_0006_conn)
    conn = pre_0006_conn
    _claim_row(conn, assignment_id="a1", claim_token_digest="a" * 64)
    conn.execute(
        "UPDATE workstation_job_dispatch SET status = 'EXPIRED', outcome_code = 'LEASE_EXPIRED', "
        "finished_at = '2026-01-01T00:05:00+00:00' WHERE assignment_id = 'a1'"
    )
    assert conn.execute("SELECT COUNT(*) AS n FROM workstation_job_dispatch").fetchone()["n"] == 1


@pytest.mark.parametrize("status,outcome_code", [
    ("CLAIMED", "RUNNER_SHUTDOWN"),  # CLAIMED must never carry an outcome code
    ("RELEASED", None),              # RELEASED must always carry one
    ("RELEASED", "LEASE_EXPIRED"),   # not one of RELEASED's own reasons
    ("EXPIRED", "RUNNER_SHUTDOWN"),  # EXPIRED must always be LEASE_EXPIRED
    ("EXPIRED", None),               # EXPIRED must always carry LEASE_EXPIRED, never NULL
])
def test_status_and_outcome_code_must_be_consistent(pre_0006_conn, status, outcome_code):
    run_migrations(pre_0006_conn)
    conn = pre_0006_conn
    finished_at = None if status == "CLAIMED" else "2026-01-01T00:05:00+00:00"
    with pytest.raises(sqlite3.IntegrityError):
        _claim_row(conn, status=status, outcome_code=outcome_code, finished_at=finished_at)


def test_lease_before_claimed_at_is_rejected(pre_0006_conn):
    run_migrations(pre_0006_conn)
    with pytest.raises(sqlite3.IntegrityError):
        _claim_row(pre_0006_conn, claimed_at="2026-01-01T00:02:00+00:00", lease_expires_at="2026-01-01T00:00:00+00:00")


def test_claim_token_digest_must_be_a_64_char_sha256_hex_length(pre_0006_conn):
    run_migrations(pre_0006_conn)
    with pytest.raises(sqlite3.IntegrityError):
        _claim_row(pre_0006_conn, claim_token_digest="too-short")


def test_claim_token_digest_is_unique_across_rows(pre_0006_conn):
    run_migrations(pre_0006_conn)
    conn = pre_0006_conn
    _claim_row(conn, assignment_id="a1", job_id=JOB, claim_token_digest="a" * 64)
    conn.execute("UPDATE workstation_job_dispatch SET status='RELEASED', outcome_code='RUNNER_SHUTDOWN', "
                 "finished_at='2026-01-01T00:01:00+00:00' WHERE assignment_id='a1'")
    with pytest.raises(sqlite3.IntegrityError):
        _claim_row(conn, assignment_id="a2", job_id=JOB_2, claim_token_digest="a" * 64)


def test_generation_must_be_at_least_one(pre_0006_conn):
    run_migrations(pre_0006_conn)
    with pytest.raises(sqlite3.IntegrityError):
        _claim_row(pre_0006_conn, generation=0)


def test_expected_indexes_exist(pre_0006_conn):
    run_migrations(pre_0006_conn)
    names = {row["name"] for row in pre_0006_conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'workstation_job_dispatch'"
    )}
    assert {
        "uq_workstation_job_dispatch_active_job",
        "uq_workstation_job_dispatch_active_runner",
        "idx_workstation_job_dispatch_job",
        "idx_workstation_job_dispatch_runner",
        "idx_workstation_job_dispatch_lease_expiry",
    } <= names
