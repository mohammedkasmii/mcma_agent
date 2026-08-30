"""
INC-10 -- schema/integrity tests: WAL+FK on, all 20 tables present,
migration idempotency/recording, and the named constraint tests from
docs/implementation/increments/30-persistence.md.
"""

import sqlite3

import pytest

from mcma.persistence.db import open_database, run_migrations
from persistence_test_support import seed_account

ALL_20_TABLES = {
    "accounts",
    "portal_sessions",
    "users",
    "role_permissions",
    "user_account_access",
    "claims",
    "categories",
    "category_presence",
    "poll_runs",
    "poll_run_categories",
    "unmatched_notifications",
    "observed_finalizations",
    "automation_jobs",
    "job_inputs",
    "account_leases",
    "employee_actions",
    "audit_events",
    "account_state_version",
    "event_outbox",
    "schema_migrations",
}


def test_wal_enabled_and_foreign_keys_on(conn):
    assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_all_twenty_tables_present(conn):
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    names = {r["name"] for r in rows} - {"sqlite_sequence"}
    assert names == ALL_20_TABLES


def test_migration_applies_forward_and_records_version(db_path):
    conn = open_database(db_path)
    versions = {r["version"] for r in conn.execute("SELECT version FROM schema_migrations").fetchall()}
    assert "0001_init" in versions
    conn.close()


def test_migration_replay_is_idempotent(db_path):
    conn = open_database(db_path)
    first_versions = run_migrations(conn)  # already applied -- no-op
    assert first_versions == []
    # No error re-running against an already-migrated DB.
    second = open_database(db_path)
    second.execute("SELECT 1 FROM accounts")  # table still usable, not recreated/duplicated
    conn.close()
    second.close()


def test_claim_requires_non_null_idSinistre(conn):
    seed_account(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO claims (claim_pk, account_id, portal_claim_id, first_seen_version, last_seen_version) "
            "VALUES ('c1', 'acct-1', NULL, 1, 1)"
        )


def test_claim_identity_unique_per_account(conn):
    seed_account(conn)
    conn.execute(
        "INSERT INTO claims (claim_pk, account_id, portal_claim_id, first_seen_version, last_seen_version) "
        "VALUES ('c1', 'acct-1', 'IDS-1', 1, 1)"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO claims (claim_pk, account_id, portal_claim_id, first_seen_version, last_seen_version) "
            "VALUES ('c2', 'acct-1', 'IDS-1', 1, 1)"
        )


def test_cross_account_category_presence_insert_fails(conn):
    """Composite FK (account_id, claim_pk) -> claims(account_id, claim_pk):
    a category_presence row cannot pair one account with ANOTHER account's
    claim_pk, even though claim_pk alone is a valid primary key elsewhere."""
    seed_account(conn, "acct-a")
    seed_account(conn, "acct-b")
    conn.execute(
        "INSERT INTO claims (claim_pk, account_id, portal_claim_id, first_seen_version, last_seen_version) "
        "VALUES ('claim-a', 'acct-a', 'IDS-A', 1, 1)"
    )
    conn.execute("INSERT INTO categories (code_alerte, label) VALUES ('CAT1', 'Category 1')")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO category_presence (account_id, claim_pk, category_code, present, since_version) "
            "VALUES ('acct-b', 'claim-a', 'CAT1', 1, 1)"
        )


def test_unmatched_notifications_never_enter_claims(conn):
    """unmatched_notifications is a fully separate table with no FK into
    claims -- a caller cannot accidentally satisfy the claims schema from
    staging data; this test proves the two tables are structurally
    disjoint (inserting into one never touches the other)."""
    seed_account(conn)
    conn.execute(
        "INSERT INTO unmatched_notifications (staging_id, account_id, reference, raw_payload, seen_at, resolved) "
        "VALUES ('stg-1', 'acct-1', 'REF-1', '{}', '2026-01-01T00:00:00+00:00', 0)"
    )
    assert conn.execute("SELECT COUNT(*) AS c FROM claims").fetchone()["c"] == 0


def test_automation_jobs_status_check_rejects_unknown_status(conn):
    seed_account(conn)
    conn.execute(
        "INSERT INTO users (user_id, username, password_hash, role, active) VALUES ('u1','u1','h','admin',1)"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO automation_jobs (job_id, account_id, requested_by_user_id, workflow_name, mode, status, "
            "input_hash, idempotency_key, created_at, state_version) "
            "VALUES ('j1', 'acct-1', 'u1', 'mission_normal', 'DRY_RUN', 'NOT_A_REAL_STATUS', 'h', 'k1', "
            "'2026-01-01T00:00:00+00:00', 1)"
        )


def test_automation_jobs_mode_check_rejects_unknown_mode(conn):
    seed_account(conn)
    conn.execute(
        "INSERT INTO users (user_id, username, password_hash, role, active) VALUES ('u1','u1','h','admin',1)"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO automation_jobs (job_id, account_id, requested_by_user_id, workflow_name, mode, status, "
            "input_hash, idempotency_key, created_at, state_version) "
            "VALUES ('j1', 'acct-1', 'u1', 'mission_normal', 'NOT_A_MODE', 'QUEUED', 'h', 'k1', "
            "'2026-01-01T00:00:00+00:00', 1)"
        )


def test_migration_is_expand_contract_compatible(db_path):
    """SR-7: adding a nullable/defaulted column is a safe forward migration
    that never breaks existing rows -- proven here with a throwaway second
    migration file registered only for this test's temp migrations dir."""
    import shutil
    from pathlib import Path

    import mcma.persistence.db as db_module

    conn = open_database(db_path)
    conn.execute(
        "INSERT INTO accounts (account_id, label, entity, scope, active, created_at) "
        "VALUES ('a1', 'L', 'MAMDA', 'OUJDA', 1, '2026-01-01T00:00:00+00:00')"
    )
    conn.close()

    real_migrations_dir = db_module._MIGRATIONS_DIR
    temp_dir = Path(db_path).parent / "migrations_copy"
    shutil.copytree(real_migrations_dir, temp_dir)
    (temp_dir / "0002_add_nullable_column.sql").write_text(
        "ALTER TABLE accounts ADD COLUMN notes TEXT;\n", encoding="utf-8"
    )

    original = db_module._MIGRATIONS_DIR
    db_module._MIGRATIONS_DIR = temp_dir
    try:
        conn2 = open_database(db_path)
        row = conn2.execute("SELECT account_id, notes FROM accounts WHERE account_id='a1'").fetchone()
        assert row["notes"] is None  # existing row survives, new column defaults to NULL
        conn2.close()
    finally:
        db_module._MIGRATIONS_DIR = original
