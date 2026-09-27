"""First-admin atomicity: the canonical accounts are provisioned INSIDE the
same transaction as the user, after the emptiness check, so a refused or
failed command has changed nothing at all."""

import pytest

from mcma.app.auth import users
from mcma.persistence.db import open_database

GOOD = "correct horse battery"
TABLES = ("accounts", "users", "user_account_access", "audit_events")


def _snapshot(conn):
    return {t: sorted(tuple(row) for row in conn.execute(f"SELECT * FROM {t}").fetchall()) for t in TABLES}


@pytest.fixture()
def raw(tmp_path):
    """A migrated database with NO canonical accounts provisioned yet."""
    connection = open_database(tmp_path / "raw.sqlite3")
    yield connection
    connection.close()


def _canonical():
    return sorted(users.canonical_account_ids())


def _insert_account(conn, account_id, label="x"):
    entity, scope = account_id.split("-")[1:]
    conn.execute(
        "INSERT INTO accounts (account_id, label, entity, scope, active, created_at) VALUES (?, ?, ?, ?, 1, 'now')",
        (account_id, label, entity.upper(), scope.upper()),
    )


def test_the_transaction_provisions_the_canonical_accounts_itself(raw):
    assert raw.execute("SELECT COUNT(*) AS c FROM accounts").fetchone()["c"] == 0
    created = users.create_first_admin(raw, "boss", GOOD)
    assert created["account_ids"] == _canonical()
    assert sorted(r["account_id"] for r in raw.execute("SELECT account_id FROM accounts").fetchall()) == _canonical()


def test_existing_user_and_missing_canonical_accounts_refuses_and_changes_nothing(raw):
    raw.execute("INSERT INTO users (user_id, username, password_hash, role, active) VALUES ('u', 'old', 'x', 'viewer', 1)")
    before = _snapshot(raw)
    with pytest.raises(users.UserInputError) as info:
        users.create_first_admin(raw, "boss", GOOD)
    assert info.value.code == "USERS_EXIST"
    assert _snapshot(raw) == before and before["accounts"] == []      # not even the canonical accounts appeared


def test_a_failure_after_canonical_provisioning_rolls_back_every_write(raw, monkeypatch):
    real = users.ensure_canonical_accounts
    seen = {}

    def provision_then_fail(connection):
        real(connection)
        seen["accounts_inside_tx"] = connection.execute("SELECT COUNT(*) AS c FROM accounts").fetchone()["c"]
        raise RuntimeError("boom after provisioning")

    monkeypatch.setattr(users, "ensure_canonical_accounts", provision_then_fail)
    before = _snapshot(raw)
    with pytest.raises(RuntimeError):
        users.create_first_admin(raw, "boss", GOOD)
    assert seen["accounts_inside_tx"] == 4                            # they WERE written, inside the transaction
    assert _snapshot(raw) == before and all(rows == [] for rows in before.values())


@pytest.mark.parametrize("failing", ["_insert_user", "_audit"])
def test_a_later_failure_also_rolls_back_the_canonical_accounts(raw, monkeypatch, failing):
    original = getattr(users, failing)

    def fail(*args, **kwargs):
        if failing == "_insert_user":
            original(*args, **kwargs)
        raise RuntimeError("late failure")

    monkeypatch.setattr(users, failing, fail)
    with pytest.raises(RuntimeError):
        users.create_first_admin(raw, "boss", GOOD)
    assert all(raw.execute(f"SELECT COUNT(*) AS c FROM {t}").fetchone()["c"] == 0 for t in TABLES)


def test_the_first_admin_gets_exactly_the_four_canonical_accounts(raw):
    raw.execute("INSERT INTO accounts (account_id, label, entity, scope, active, created_at) "
                "VALUES ('acct-legacy', 'legacy', 'MCMA', 'LEGACY', 1, 'now')")
    created = users.create_first_admin(raw, "boss", GOOD)
    assert created["account_ids"] == _canonical() and "acct-legacy" not in created["account_ids"]
    granted = sorted(r["account_id"] for r in raw.execute("SELECT account_id FROM user_account_access").fetchall())
    assert granted == _canonical()


def test_partial_canonical_state_is_completed_atomically_on_success(raw):
    for account_id in _canonical()[:2]:
        _insert_account(raw, account_id)
    created = users.create_first_admin(raw, "boss", GOOD)
    assert created["account_ids"] == _canonical()
    assert raw.execute("SELECT COUNT(*) AS c FROM accounts").fetchone()["c"] == 4


def test_partial_canonical_state_is_left_exactly_as_it_was_on_failure(raw, monkeypatch):
    _insert_account(raw, _canonical()[0])
    before = _snapshot(raw)
    monkeypatch.setattr(users, "_audit", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("late")))
    with pytest.raises(RuntimeError):
        users.create_first_admin(raw, "boss", GOOD)
    assert _snapshot(raw) == before and len(before["accounts"]) == 1


def test_invalid_input_is_rejected_before_any_write_including_accounts(raw):
    for username, password in (("x", GOOD), ("boss", "short")):
        with pytest.raises(users.UserInputError):
            users.create_first_admin(raw, username, password)
    assert raw.execute("SELECT COUNT(*) AS c FROM accounts").fetchone()["c"] == 0
