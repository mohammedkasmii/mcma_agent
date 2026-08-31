"""Correction batch -- migration 0002: (entity, scope) uniqueness on
accounts, and automation_jobs' status CHECK gaining
AWAITING_HUMAN_CONFIRMATION / HUMAN_CONFIRMED_COMPLETE via a safe
create-copy-drop-rename rebuild. Exercised starting from a DATABASE
ALREADY POPULATED under 0001 alone (not just an empty database) so the
rebuild's data-preservation guarantee is actually proven, not assumed.
"""

import sqlite3

import pytest

import mcma.persistence.db as db_module
from mcma.persistence.db import _split_statements, connect, run_migrations


def _apply_0001_only(conn: sqlite3.Connection) -> None:
    """Replays exactly 0001_init.sql by hand (bypassing run_migrations, which
    would also apply every later migration) so the test can populate a
    database that has only ever seen the original schema."""
    path = db_module._MIGRATIONS_DIR / "0001_init.sql"
    statements = _split_statements(path.read_text(encoding="utf-8"))
    conn.execute("BEGIN")
    for statement in statements:
        conn.execute(statement)
    conn.execute(
        "INSERT INTO schema_migrations (version, applied_at) VALUES ('0001_init', '2026-01-01T00:00:00+00:00')"
    )
    conn.execute("COMMIT")


@pytest.fixture()
def populated_0001_conn(db_path):
    conn = connect(db_path)
    _apply_0001_only(conn)

    conn.execute(
        "INSERT INTO accounts (account_id, label, entity, scope, active, created_at) "
        "VALUES ('acct-mcma-oujda', 'MCMA Oujda', 'MCMA', 'OUJDA', 1, '2026-01-01T00:00:00+00:00')"
    )
    conn.execute(
        "INSERT INTO users (user_id, username, password_hash, role, active) VALUES ('u1', 'alice', 'h', 'admin', 1)"
    )
    conn.execute(
        "INSERT INTO automation_jobs (job_id, account_id, requested_by_user_id, workflow_name, mode, status, "
        "input_hash, idempotency_key, created_at, state_version) VALUES "
        "('job-1', 'acct-mcma-oujda', 'u1', 'mission_normal', 'EXECUTE', 'READY_FOR_HUMAN_REVIEW', "
        "'h', 'k1', '2026-01-01T00:00:00+00:00', 3)"
    )
    conn.execute(
        "INSERT INTO job_inputs (job_id, content_hash, ciphertext, pii_class, created_at, expires_at) "
        "VALUES ('job-1', 'h', X'00', 'CONTAINS_PII', '2026-01-01T00:00:00+00:00', '2026-02-01T00:00:00+00:00')"
    )
    conn.execute("INSERT INTO account_state_version (account_id, version) VALUES ('acct-mcma-oujda', 3)")
    conn.execute(
        "INSERT INTO event_outbox (account_id, account_state_version, aggregate, type, payload_json, created_at) "
        "VALUES ('acct-mcma-oujda', 3, 'job', 'JOB_STATUS_CHANGED', '{}', '2026-01-01T00:00:00+00:00')"
    )
    yield conn
    conn.close()


def test_upgrade_preserves_existing_rows_across_every_touched_table(populated_0001_conn):
    conn = populated_0001_conn
    applied = run_migrations(conn)
    assert "0002_shared_portal_accounts_and_human_handoff" in applied

    account = conn.execute("SELECT * FROM accounts WHERE account_id='acct-mcma-oujda'").fetchone()
    assert account["entity"] == "MCMA" and account["scope"] == "OUJDA"

    job = conn.execute("SELECT * FROM automation_jobs WHERE job_id='job-1'").fetchone()
    assert job["status"] == "READY_FOR_HUMAN_REVIEW"
    assert job["state_version"] == 3
    assert job["requested_by_user_id"] == "u1"

    job_input = conn.execute("SELECT * FROM job_inputs WHERE job_id='job-1'").fetchone()
    assert job_input["content_hash"] == "h"

    version_row = conn.execute(
        "SELECT version FROM account_state_version WHERE account_id='acct-mcma-oujda'"
    ).fetchone()
    assert version_row["version"] == 3

    outbox_row = conn.execute("SELECT * FROM event_outbox WHERE account_id='acct-mcma-oujda'").fetchone()
    assert outbox_row["type"] == "JOB_STATUS_CHANGED"


def test_upgrade_preserves_foreign_keys_and_unique_constraint(populated_0001_conn):
    conn = populated_0001_conn
    run_migrations(conn)

    # account_id/requested_by_user_id FKs still enforced on the rebuilt table.
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO automation_jobs (job_id, account_id, requested_by_user_id, workflow_name, mode, status, "
            "input_hash, idempotency_key, created_at, state_version) VALUES "
            "('job-bad', 'no-such-account', 'u1', 'mission_normal', 'DRY_RUN', 'QUEUED', 'h', 'k2', "
            "'2026-01-01T00:00:00+00:00', 1)"
        )

    # UNIQUE(account_id, idempotency_key) still enforced.
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO automation_jobs (job_id, account_id, requested_by_user_id, workflow_name, mode, status, "
            "input_hash, idempotency_key, created_at, state_version) VALUES "
            "('job-dup', 'acct-mcma-oujda', 'u1', 'mission_normal', 'DRY_RUN', 'QUEUED', 'h', 'k1', "
            "'2026-01-01T00:00:00+00:00', 1)"
        )

    # job_inputs' FK into automation_jobs(job_id) still resolves post-rebuild.
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO job_inputs (job_id, content_hash, ciphertext, pii_class, created_at, expires_at) "
            "VALUES ('no-such-job', 'h', X'00', 'CONTAINS_PII', '2026-01-01T00:00:00+00:00', '2026-02-01T00:00:00+00:00')"
        )

    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    assert violations == []


def test_upgrade_accepts_the_two_new_statuses(populated_0001_conn):
    conn = populated_0001_conn
    run_migrations(conn)
    conn.execute("UPDATE automation_jobs SET status='AWAITING_HUMAN_CONFIRMATION' WHERE job_id='job-1'")
    conn.execute("UPDATE automation_jobs SET status='HUMAN_CONFIRMED_COMPLETE' WHERE job_id='job-1'")
    row = conn.execute("SELECT status FROM automation_jobs WHERE job_id='job-1'").fetchone()
    assert row["status"] == "HUMAN_CONFIRMED_COMPLETE"


def test_upgrade_still_rejects_an_unknown_status(populated_0001_conn):
    conn = populated_0001_conn
    run_migrations(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE automation_jobs SET status='NOT_A_REAL_STATUS' WHERE job_id='job-1'")


def test_upgrade_rejects_duplicate_entity_scope_pairing(populated_0001_conn):
    conn = populated_0001_conn
    run_migrations(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO accounts (account_id, label, entity, scope, active, created_at) "
            "VALUES ('acct-mcma-oujda-2', 'A second MCMA Oujda for another employee', 'MCMA', 'OUJDA', 1, "
            "'2026-01-01T00:00:00+00:00')"
        )


def test_upgrade_still_allows_the_other_three_profiles(populated_0001_conn):
    conn = populated_0001_conn
    run_migrations(conn)
    for entity, scope in (("MCMA", "NADOR"), ("MAMDA", "OUJDA"), ("MAMDA", "NADOR")):
        conn.execute(
            "INSERT INTO accounts (account_id, label, entity, scope, active, created_at) VALUES (?, ?, ?, ?, 1, "
            "'2026-01-01T00:00:00+00:00')",
            (f"acct-{entity}-{scope}", f"{entity} {scope}", entity, scope),
        )
    count = conn.execute("SELECT COUNT(*) AS c FROM accounts").fetchone()["c"]
    assert count == 4


def test_foreign_keys_pragma_restored_after_migration(populated_0001_conn):
    conn = populated_0001_conn
    run_migrations(conn)
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_migration_replay_after_0002_is_idempotent(populated_0001_conn):
    conn = populated_0001_conn
    first = run_migrations(conn)
    assert "0002_shared_portal_accounts_and_human_handoff" in first
    second = run_migrations(conn)
    assert second == []
    # still usable, not duplicated/recreated a second time
    row = conn.execute("SELECT status FROM automation_jobs WHERE job_id='job-1'").fetchone()
    assert row["status"] == "READY_FOR_HUMAN_REVIEW"
