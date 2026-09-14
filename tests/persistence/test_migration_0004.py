"""Migration 0004 -- notification freshness. Applied to a database already
populated under 0001-0003 (not just an empty one), so "existing presence
rows stay seen" and the baseline backfill are proven rather than assumed.
Synthetic data only."""

import shutil

import pytest

import mcma.persistence.db as db_module
from mcma.notifications.presence import apply_category_result
from mcma.persistence.db import connect, run_migrations
from mcma.persistence.repositories.claims import CategoryPresenceRepository, PollRunsRepository

ACCOUNT = "acct-mamda-oujda"
POLLED = "CAT_POLLED"
NEVER_COMPLETE = "CAT_FAILED_ONLY"


@pytest.fixture()
def pre_0004_conn(tmp_path, monkeypatch):
    """A database migrated through 0003 only, holding one presence row that
    was on screen before freshness existed."""
    pre_dir = tmp_path / "migrations_pre_0004"
    pre_dir.mkdir()
    for path in db_module._MIGRATIONS_DIR.glob("*.sql"):
        if path.name < "0004":
            shutil.copy(path, pre_dir / path.name)
    monkeypatch.setattr(db_module, "_MIGRATIONS_DIR", pre_dir)

    conn = connect(tmp_path / "mcma_test.sqlite3")
    run_migrations(conn)
    conn.execute(
        "INSERT INTO accounts (account_id, label, entity, scope, active, created_at) "
        "VALUES (?, 'MAMDA Oujda', 'MAMDA', 'OUJDA', 1, '2026-01-01T00:00:00+00:00')",
        (ACCOUNT,),
    )
    for code in (POLLED, NEVER_COMPLETE):
        conn.execute("INSERT INTO categories (code_alerte, label) VALUES (?, ?)", (code, code))
    conn.execute(
        "INSERT INTO claims (claim_pk, account_id, portal_claim_id, first_seen_version, last_seen_version) "
        "VALUES ('claim-old', ?, 'OLD', 1, 1)",
        (ACCOUNT,),
    )
    PollRunsRepository(conn).create("poll-1", ACCOUNT, "2026-01-01T00:00:00+00:00", "PARTIAL", True)
    conn.execute(
        "INSERT INTO poll_run_categories (poll_run_id, category_code, status, session_valid, completed_at) "
        "VALUES ('poll-1', ?, 'COMPLETE', 1, '2026-01-01T00:05:00+00:00')",
        (POLLED,),
    )
    conn.execute(
        "INSERT INTO poll_run_categories (poll_run_id, category_code, status, session_valid) "
        "VALUES ('poll-1', ?, 'FAILED', 0)",
        (NEVER_COMPLETE,),
    )
    poll_version = conn.execute("SELECT rowid AS v FROM poll_runs WHERE poll_run_id='poll-1'").fetchone()["v"]
    conn.execute(
        "INSERT INTO category_presence (account_id, claim_pk, category_code, present, presence_status, "
        "consecutive_absence_count, last_complete_poll_version, since_version, last_seen_poll_run_id) "
        "VALUES (?, 'claim-old', ?, 1, 'ACTIVE', 0, ?, ?, 'poll-1')",
        (ACCOUNT, POLLED, poll_version, poll_version),
    )

    monkeypatch.undo()  # the real migrations dir again, so run_migrations now applies 0004
    yield conn, poll_version
    conn.close()


def test_existing_presence_rows_stay_seen_after_migration(pre_0004_conn):
    conn, poll_version = pre_0004_conn
    assert "0004_notification_freshness" in run_migrations(conn)

    row = CategoryPresenceRepository(conn).get(ACCOUNT, "claim-old", POLLED)
    assert row["unread"] == 0
    assert row["seen_at"] is None
    assert row["appeared_poll_version"] == poll_version


def test_baseline_is_backfilled_only_from_complete_category_polls(pre_0004_conn):
    conn, poll_version = pre_0004_conn
    run_migrations(conn)

    baselines = {
        r["category_code"]: r for r in conn.execute("SELECT * FROM category_baselines").fetchall()
    }
    assert set(baselines) == {POLLED}
    assert baselines[POLLED]["account_id"] == ACCOUNT
    assert baselines[POLLED]["baseline_poll_version"] == poll_version
    assert baselines[POLLED]["established_at"] == "2026-01-01T00:05:00+00:00"


def test_after_migration_existing_stays_seen_and_a_real_arrival_is_new(pre_0004_conn):
    conn, _ = pre_0004_conn
    run_migrations(conn)
    conn.execute(
        "INSERT INTO claims (claim_pk, account_id, portal_claim_id, first_seen_version, last_seen_version) "
        "VALUES ('claim-new', ?, 'NEW', 2, 2)",
        (ACCOUNT,),
    )
    PollRunsRepository(conn).create("poll-2", ACCOUNT, "2026-01-02T00:00:00+00:00", "COMPLETE", True)
    for claim_pk in ("claim-old", "claim-new"):
        apply_category_result(
            conn, ACCOUNT, claim_pk, POLLED, poll_run_id="poll-2", category_status="COMPLETE",
            session_valid=True, observed_present=True,
        )

    repo = CategoryPresenceRepository(conn)
    assert repo.get(ACCOUNT, "claim-old", POLLED)["unread"] == 0
    assert repo.get(ACCOUNT, "claim-new", POLLED)["unread"] == 1


def test_unread_is_constrained_to_zero_or_one(pre_0004_conn):
    import sqlite3

    conn, _ = pre_0004_conn
    run_migrations(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE category_presence SET unread = 2 WHERE claim_pk = 'claim-old'")
