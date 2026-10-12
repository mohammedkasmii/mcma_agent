"""Migration 0009 -- notification onboarding requests. Applied on top of a
database already populated under 0001-0008, proving the forward migration
is additive and that its CHECK constraints and partial unique indexes hold
the state-machine invariants in the database itself."""

import shutil
import sqlite3

import pytest

import mcma.persistence.db as db_module
from mcma.persistence.db import connect, run_migrations

USER, ENROLL, RUNNER, RUNNER_2 = "user-1", "enroll-1", "runner-1", "runner-2"
ACCOUNTS = ("acct-mcma-oujda", "acct-mcma-nador", "acct-mamda-oujda", "acct-mamda-nador")
T0 = "2026-01-01T00:00:00+00:00"
T1 = "2026-01-01T00:05:00+00:00"


@pytest.fixture()
def pre_conn(tmp_path, monkeypatch):
    pre_dir = tmp_path / "pre"
    pre_dir.mkdir()
    for path in db_module._MIGRATIONS_DIR.glob("*.sql"):
        if path.name < "0009":
            shutil.copy(path, pre_dir / path.name)
    monkeypatch.setattr(db_module, "_MIGRATIONS_DIR", pre_dir)
    conn = connect(tmp_path / "t.sqlite3")
    run_migrations(conn)
    conn.execute("INSERT INTO users (user_id, username, password_hash, role, active) VALUES (?, 'u1', 'h', 'operator', 1)", (USER,))
    for account_id in ACCOUNTS:
        entity, scope = account_id.split("-")[1:]
        conn.execute(
            "INSERT INTO accounts (account_id, label, entity, scope, active, created_at) VALUES (?, ?, ?, ?, 1, ?)",
            (account_id, account_id, entity.upper(), scope.upper(), T0),
        )
    for n, runner in enumerate((RUNNER, RUNNER_2)):
        conn.execute(
            "INSERT INTO runner_enrollments (enrollment_id, code_digest, target_user_id, created_by_user_id, created_at, "
            "expires_at, consumed_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (f"e{n}", str(n) * 64, USER, USER, T0, T1, T0),
        )
        conn.execute(
            "INSERT INTO runners (runner_id, user_id, credential_digest, runner_label, status, enrollment_id, created_at, "
            "revoked_at) VALUES (?, ?, ?, 'R', ?, ?, ?, ?)",
            (runner, USER, str(n + 5) * 64, "ACTIVE" if n == 0 else "REVOKED", f"e{n}", T0, None if n == 0 else T0),
        )
    monkeypatch.undo()
    yield conn
    conn.close()


@pytest.fixture()
def conn(pre_conn):
    assert "0009_notification_onboarding" in run_migrations(pre_conn)
    return pre_conn


def _insert(conn, **kw):
    cols = {
        "request_id": "a" * 32, "account_id": ACCOUNTS[0], "user_id": USER, "runner_id": RUNNER, "generation": 1,
        "status": "PENDING", "created_at": T0, "expires_at": T1, "updated_at": T0,
    }
    cols.update(kw)
    conn.execute(
        f"INSERT INTO notification_onboarding_requests ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
        tuple(cols.values()),
    )


CLAIMED = dict(status="CLAIMED", claim_token_digest="d" * 64, claimed_at=T0, lease_expires_at=T1)


def test_migration_is_forward_only_and_leaves_old_tables_alone(pre_conn):
    before = {r["name"] for r in pre_conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    applied = run_migrations(pre_conn)
    assert applied == ["0009_notification_onboarding"]
    after = {r["name"] for r in pre_conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert after - before == {"notification_onboarding_requests"}
    assert run_migrations(pre_conn) == []


def test_no_sensitive_column_exists(conn):
    columns = {r["name"] for r in conn.execute("PRAGMA table_info(notification_onboarding_requests)")}
    assert "claim_token" not in columns and "claim_token_digest" in columns
    for banned in ("storage_state", "cookie", "password", "otp", "secret", "credential"):
        assert not any(banned in c for c in columns), (banned, columns)


@pytest.mark.parametrize("account", ACCOUNTS)
def test_all_four_accounts_accepted(conn, account):
    _insert(conn, account_id=account)


def test_non_canonical_account_rejected(conn):
    conn.execute("INSERT INTO accounts (account_id, label, entity, scope, active, created_at) VALUES ('acct-x','x','MCMA','X',1,?)", (T0,))
    with pytest.raises(sqlite3.IntegrityError):
        _insert(conn, account_id="acct-x")


def test_one_active_request_per_account(conn):
    _insert(conn)
    with pytest.raises(sqlite3.IntegrityError):
        _insert(conn, request_id="b" * 32, generation=2)


def test_terminal_request_does_not_block_new_one(conn):
    _insert(conn, status="FAILED", outcome_code="LOGIN_TIMED_OUT", finished_at=T1)
    _insert(conn, request_id="b" * 32, generation=2)


def test_one_active_request_per_runner(conn):
    _insert(conn)
    with pytest.raises(sqlite3.IntegrityError):
        _insert(conn, request_id="b" * 32, account_id=ACCOUNTS[1])


def test_generation_unique_per_account(conn):
    _insert(conn, status="CANCELLED", outcome_code="CANCELLED_BY_USER", finished_at=T1)
    with pytest.raises(sqlite3.IntegrityError):
        _insert(conn, request_id="b" * 32)


def test_claimed_requires_digest_and_lease(conn):
    with pytest.raises(sqlite3.IntegrityError):
        _insert(conn, status="CLAIMED")


def test_pending_cannot_carry_claim_material(conn):
    with pytest.raises(sqlite3.IntegrityError):
        _insert(conn, claim_token_digest="d" * 64)


def test_digest_is_unique_and_64_chars(conn):
    with pytest.raises(sqlite3.IntegrityError):
        _insert(conn, **{**CLAIMED, "claim_token_digest": "short"})
    _insert(conn, **CLAIMED)
    conn.execute("UPDATE notification_onboarding_requests SET status='EXPIRED', outcome_code='LEASE_EXPIRED', finished_at=?", (T1,))
    with pytest.raises(sqlite3.IntegrityError):
        _insert(conn, request_id="b" * 32, generation=2, **CLAIMED)


@pytest.mark.parametrize("status,outcome", [
    ("SUCCEEDED", "LOGIN_TIMED_OUT"), ("FAILED", "SESSION_STORED"), ("CANCELLED", "LEASE_EXPIRED"),
    ("EXPIRED", "CANCELLED_BY_USER"), ("FAILED", "ANYTHING"), ("FAILED", None),
])
def test_terminal_outcome_must_match_status(conn, status, outcome):
    with pytest.raises(sqlite3.IntegrityError):
        _insert(conn, status=status, outcome_code=outcome, finished_at=T1, claim_token_digest="d" * 64)


@pytest.mark.parametrize("status,outcome", [
    ("SUCCEEDED", "SESSION_STORED"), ("FAILED", "UPLOAD_FAILED"), ("FAILED", "INTERNAL_ERROR"),
    ("CANCELLED", "RUNNER_SHUTDOWN"), ("EXPIRED", "REQUEST_EXPIRED"), ("EXPIRED", "LEASE_EXPIRED"),
])
def test_terminal_outcome_accepted(conn, status, outcome):
    _insert(conn, status=status, outcome_code=outcome, finished_at=T1, claim_token_digest="d" * 64)


def test_active_request_cannot_have_outcome_and_terminal_needs_finished_at(conn):
    with pytest.raises(sqlite3.IntegrityError):
        _insert(conn, outcome_code="INTERNAL_ERROR")
    with pytest.raises(sqlite3.IntegrityError):
        _insert(conn, status="CANCELLED", outcome_code="CANCELLED_BY_USER")


def test_phase_enum(conn):
    with pytest.raises(sqlite3.IntegrityError):
        _insert(conn, phase="NOPE", **CLAIMED)
    for phase in ("OPENING_WINDOW", "WINDOW_OPENED", "WAITING_FOR_LOGIN"):
        conn.execute("DELETE FROM notification_onboarding_requests")
        _insert(conn, phase=phase, **CLAIMED)


def test_status_enum_closed(conn):
    with pytest.raises(sqlite3.IntegrityError):
        _insert(conn, status="RUNNING")


def test_expiry_not_before_creation(conn):
    with pytest.raises(sqlite3.IntegrityError):
        _insert(conn, expires_at="2025-01-01T00:00:00+00:00")


def test_runner_must_exist(conn):
    conn.execute("PRAGMA foreign_keys=ON")
    with pytest.raises(sqlite3.IntegrityError):
        _insert(conn, runner_id="ghost")
