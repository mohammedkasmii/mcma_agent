"""The shared platform-user service (used by the offline first-admin command
and the admin API): validation, transactions, protections, audit."""

import threading

import pytest

from mcma.app.auth import users
from mcma.app.auth.passwords import verify_password
from mcma.app.provisioning import ensure_canonical_accounts
from mcma.persistence.db import open_database

GOOD = "correct horse battery"


@pytest.fixture()
def conn(tmp_path):
    connection = open_database(tmp_path / "users.sqlite3")
    ensure_canonical_accounts(connection)
    yield connection
    connection.close()


def _ids(conn):
    return sorted(r["account_id"] for r in conn.execute("SELECT account_id FROM accounts").fetchall())


# ------------------------------- usernames ------------------------------------ #


@pytest.mark.parametrize("raw, expected", [("  Admin ", "admin"), ("Ali.B-2_x", "ali.b-2_x"), ("ＡＤＭＩＮ", "admin")])
def test_usernames_are_normalized_consistently(raw, expected):
    assert users.normalize_username(raw) == expected


@pytest.mark.parametrize("raw", ["", "ab", "a" * 33, "-lead", ".lead", "sp ace", "é-accent", "a/b", "x;drop", None, 5])
def test_invalid_usernames_get_a_french_error(raw):
    with pytest.raises(users.UserInputError) as info:
        users.normalize_username(raw)
    assert info.value.code == "USERNAME_INVALID" and "nom d'utilisateur" in info.value.message.lower()


# ------------------------------- password policy -------------------------------- #


@pytest.mark.parametrize("password, code", [
    ("", "PASSWORD_TOO_SHORT"), (None, "PASSWORD_TOO_SHORT"), ("short-pw", "PASSWORD_TOO_SHORT"),
    ("x" * 129, "PASSWORD_TOO_LONG"),
    ("my-admin-is-alice-yes", "PASSWORD_CONTAINS_USERNAME"),
    ("aaaaaaaaaaaaaaaa", "PASSWORD_TOO_SIMPLE"), ("abcdefghijklmnop", "PASSWORD_TOO_SIMPLE"),
    ("121212121212", "PASSWORD_TOO_SIMPLE"),
])
def test_password_policy_rejections_have_stable_codes_and_french_messages(password, code):
    with pytest.raises(users.UserInputError) as info:
        users.validate_password(password, "alice")
    assert info.value.code == code
    assert any(word in info.value.message for word in ("mot de passe", "Mot de passe"))
    if password and len(password) > 4:
        assert password not in info.value.message                 # the message never echoes the input


def test_a_reasonable_passphrase_is_accepted():
    assert users.validate_password(GOOD, "alice") == GOOD


# ------------------------------- first admin ------------------------------------ #


def test_first_admin_is_an_active_admin_with_every_canonical_account(conn):
    created = users.create_first_admin(conn, " Boss ", GOOD)
    assert (created["username"], created["role"], created["active"]) == ("boss", "admin", True)
    assert created["account_ids"] == _ids(conn) and len(created["account_ids"]) == 4
    row = conn.execute("SELECT password_hash FROM users").fetchone()
    assert row["password_hash"].startswith("$argon2id$") and GOOD not in row["password_hash"]
    assert verify_password(row["password_hash"], GOOD)
    audit = conn.execute("SELECT action, actor_user_id, after_hash FROM audit_events").fetchall()
    assert [(a["action"], a["actor_user_id"]) for a in audit] == [("user.first_admin_created", None)]
    assert GOOD not in str(dict(audit[0])) and audit[0]["after_hash"] and len(audit[0]["after_hash"]) == 64


def test_first_admin_is_refused_when_any_user_exists_and_nothing_changes(conn):
    users.create_first_admin(conn, "boss", GOOD)
    before = (conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"],
              conn.execute("SELECT COUNT(*) AS c FROM user_account_access").fetchone()["c"],
              conn.execute("SELECT COUNT(*) AS c FROM audit_events").fetchone()["c"])
    with pytest.raises(users.UserInputError) as info:
        users.create_first_admin(conn, "second", GOOD)
    assert info.value.code == "USERS_EXIST" and "Rien n'a été modifié" in info.value.message
    after = (conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"],
             conn.execute("SELECT COUNT(*) AS c FROM user_account_access").fetchone()["c"],
             conn.execute("SELECT COUNT(*) AS c FROM audit_events").fetchone()["c"])
    assert after == before


def test_even_an_inactive_or_non_admin_existing_user_blocks_first_admin(conn):
    conn.execute("INSERT INTO users (user_id, username, password_hash, role, active) VALUES ('u', 'old', 'x', 'viewer', 0)")
    with pytest.raises(users.UserInputError, match="existent déjà"):
        users.create_first_admin(conn, "boss", GOOD)


@pytest.mark.parametrize("step", ["_audit", "_insert_user"])
def test_first_admin_rolls_back_everything_when_any_step_fails(conn, monkeypatch, step):
    original = getattr(users, step)

    def boom(*args, **kwargs):
        if step == "_insert_user":
            original(*args, **kwargs)          # the row IS inserted, then a later failure happens
            raise RuntimeError("disk full")
        raise RuntimeError("audit write failed")

    monkeypatch.setattr(users, step, boom)
    with pytest.raises(RuntimeError):
        users.create_first_admin(conn, "boss", GOOD)
    for table in ("users", "user_account_access", "audit_events"):
        assert conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()["c"] == 0, table
    monkeypatch.undo()
    assert users.create_first_admin(conn, "boss", GOOD)["username"] == "boss"      # and it is retryable


def test_first_admin_validates_username_and_password_before_touching_the_database(conn):
    with pytest.raises(users.UserInputError):
        users.create_first_admin(conn, "x", GOOD)
    with pytest.raises(users.UserInputError):
        users.create_first_admin(conn, "boss", "short")
    assert users.user_count(conn) == 0



# ------------------------------- create / update -------------------------------- #


def _admin(conn):
    return users.create_first_admin(conn, "boss", GOOD)["user_id"]


def test_create_user_with_role_and_selected_accounts(conn):
    actor = _admin(conn)
    accounts = _ids(conn)[:2]
    created = users.create_user(conn, actor_user_id=actor, username="Sara", password=GOOD, role="operator", account_ids=accounts)
    assert created["username"] == "sara" and created["role"] == "operator" and created["account_ids"] == sorted(accounts)
    assert "password" not in str(created) and "hash" not in str(created)
    audit = conn.execute("SELECT action, actor_user_id FROM audit_events ORDER BY rowid").fetchall()
    assert audit[-1]["action"] == "user.created" and audit[-1]["actor_user_id"] == actor


def test_usernames_are_unique_case_insensitively(conn):
    actor = _admin(conn)
    users.create_user(conn, actor_user_id=actor, username="sara", password=GOOD, role="viewer", account_ids=[])
    for variant in ("SARA", "Sara", " sara "):
        with pytest.raises(users.UserInputError) as info:
            users.create_user(conn, actor_user_id=actor, username=variant, password=GOOD, role="viewer", account_ids=[])
        assert info.value.code == "USERNAME_TAKEN" and info.value.status == 409


def test_role_and_account_validation(conn):
    actor = _admin(conn)
    for bad_role in ("root", "", None, "ADMIN"):
        with pytest.raises(users.UserInputError) as info:
            users.create_user(conn, actor_user_id=actor, username="tom", password=GOOD, role=bad_role, account_ids=[])
        assert info.value.code == "ROLE_INVALID"
    for bad_accounts in (["acct-unknown"], ["acct-mcma-oujda", "nope"], "acct-mcma-oujda", [1]):
        with pytest.raises(users.UserInputError) as info:
            users.create_user(conn, actor_user_id=actor, username="tom", password=GOOD, role="viewer", account_ids=bad_accounts)
        assert info.value.code == "ACCOUNT_UNKNOWN"
    assert users.user_count(conn) == 1                                       # nothing half-created


def test_a_non_canonical_account_row_cannot_be_assigned(conn):
    conn.execute("INSERT INTO accounts (account_id, label, entity, scope, active, created_at) "
                 "VALUES ('acct-extra', 'x', 'MCMA', 'EXTRA', 1, 'now')")
    with pytest.raises(users.UserInputError) as info:
        users.create_user(conn, actor_user_id=_admin(conn), username="tom", password=GOOD, role="viewer", account_ids=["acct-extra"])
    assert info.value.code == "ACCOUNT_UNKNOWN"


def test_update_replaces_the_account_set_atomically(conn):
    actor = _admin(conn)
    ids = _ids(conn)
    uid = users.create_user(conn, actor_user_id=actor, username="sara", password=GOOD, role="viewer", account_ids=ids[:3])["user_id"]
    view, ended = users.update_user(conn, actor_user_id=actor, user_id=uid, account_ids=ids[2:])
    assert view["account_ids"] == ids[2:] and ended is False
    view, _ = users.update_user(conn, actor_user_id=actor, user_id=uid, account_ids=[])
    assert view["account_ids"] == []


def test_failed_update_changes_nothing(conn):
    actor = _admin(conn)
    uid = users.create_user(conn, actor_user_id=actor, username="sara", password=GOOD, role="viewer", account_ids=_ids(conn)[:1])["user_id"]
    with pytest.raises(users.UserInputError):
        users.update_user(conn, actor_user_id=actor, user_id=uid, active=False, role="nonsense")
    row = conn.execute("SELECT role, active FROM users WHERE user_id = ?", (uid,)).fetchone()
    assert (row["role"], row["active"]) == ("viewer", 1)


def test_unknown_user_is_404(conn):
    with pytest.raises(users.UserInputError) as info:
        users.update_user(conn, actor_user_id=_admin(conn), user_id="nope", active=False)
    assert (info.value.code, info.value.status) == ("USER_NOT_FOUND", 404)


# ---------------------- last administrator / self lockout ----------------------- #


def test_the_last_active_administrator_can_never_lose_admin(conn):
    boss = _admin(conn)
    for kwargs in ({"active": False}, {"role": "operator"}):
        with pytest.raises(users.UserInputError) as info:
            users.update_user(conn, actor_user_id="someone-else", user_id=boss, **kwargs)
        assert info.value.code == "LAST_ADMIN"
    assert conn.execute("SELECT role, active FROM users").fetchone()["active"] == 1


def test_an_admin_cannot_deactivate_or_demote_their_own_account(conn):
    boss = _admin(conn)
    other = users.create_user(conn, actor_user_id=boss, username="deputy", password=GOOD, role="admin", account_ids=[])["user_id"]
    for kwargs in ({"active": False}, {"role": "viewer"}):
        with pytest.raises(users.UserInputError) as info:
            users.update_user(conn, actor_user_id=boss, user_id=boss, **kwargs)
        assert info.value.code == "SELF_LOCKOUT"
    # ...but one admin may deactivate ANOTHER while a second stays active
    view, ended = users.update_user(conn, actor_user_id=boss, user_id=other, active=False)
    assert view["active"] is False and ended is True
    # now the remaining admin is the last active one
    with pytest.raises(users.UserInputError) as info:
        users.update_user(conn, actor_user_id=other, user_id=boss, active=False)
    assert info.value.code == "LAST_ADMIN"


def test_inactive_admin_does_not_count_as_a_second_admin(conn):
    boss = _admin(conn)
    ghost = users.create_user(conn, actor_user_id=boss, username="ghost", password=GOOD, role="admin", account_ids=[])["user_id"]
    users.update_user(conn, actor_user_id=boss, user_id=ghost, active=False)
    with pytest.raises(users.UserInputError) as info:
        users.update_user(conn, actor_user_id=ghost, user_id=boss, role="viewer")
    assert info.value.code == "LAST_ADMIN"


def test_two_admins_racing_to_demote_each_other_cannot_leave_zero(conn):
    a = _admin(conn)
    b = users.create_user(conn, actor_user_id=a, username="deputy", password=GOOD, role="admin", account_ids=[])["user_id"]
    outcomes = []

    def demote(actor, target):
        try:
            users.update_user(conn, actor_user_id=actor, user_id=target, role="viewer")
            outcomes.append("ok")
        except users.UserInputError as exc:
            outcomes.append(exc.code)

    threads = [threading.Thread(target=demote, args=(a, b)), threading.Thread(target=demote, args=(b, a))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert conn.execute("SELECT COUNT(*) AS c FROM users WHERE role='admin' AND active=1").fetchone()["c"] >= 1
    assert outcomes.count("ok") == 1


# ------------------------------- password reset --------------------------------- #


def test_reset_password_changes_the_hash_and_never_stores_plaintext(conn):
    actor = _admin(conn)
    uid = users.create_user(conn, actor_user_id=actor, username="sara", password=GOOD, role="viewer", account_ids=[])["user_id"]
    old = conn.execute("SELECT password_hash FROM users WHERE user_id = ?", (uid,)).fetchone()["password_hash"]
    new_secret = "an entirely different phrase"
    users.reset_password(conn, actor_user_id=actor, user_id=uid, password=new_secret)
    row = conn.execute("SELECT password_hash FROM users WHERE user_id = ?", (uid,)).fetchone()
    assert row["password_hash"] != old and verify_password(row["password_hash"], new_secret)
    assert not verify_password(row["password_hash"], GOOD)
    stored = " ".join(str(dict(r)) for r in conn.execute("SELECT * FROM audit_events").fetchall())
    assert new_secret not in stored and row["password_hash"] not in stored


def test_reset_enforces_the_same_password_policy(conn):
    actor = _admin(conn)
    uid = users.create_user(conn, actor_user_id=actor, username="sara", password=GOOD, role="viewer", account_ids=[])["user_id"]
    for bad, code in (("short", "PASSWORD_TOO_SHORT"), ("sara-sara-sara-sara", "PASSWORD_CONTAINS_USERNAME")):
        with pytest.raises(users.UserInputError) as info:
            users.reset_password(conn, actor_user_id=actor, user_id=uid, password=bad)
        assert info.value.code == code
    assert verify_password(conn.execute("SELECT password_hash FROM users WHERE user_id=?", (uid,)).fetchone()["password_hash"], GOOD)


# -------------------------------- no secrets in views ---------------------------- #


def test_user_views_never_carry_hashes_or_passwords(conn):
    _admin(conn)
    for view in users.list_users(conn):
        assert set(view) == {"user_id", "username", "role", "active", "account_ids"}


def test_administrators_always_hold_every_portal_account(conn):
    boss = _admin(conn)
    deputy = users.create_user(conn, actor_user_id=boss, username="deputy", password=GOOD, role="admin", account_ids=[])
    assert deputy["account_ids"] == _ids(conn)
    viewer = users.create_user(conn, actor_user_id=boss, username="viewer1", password=GOOD, role="viewer",
                               account_ids=_ids(conn)[:1])["user_id"]
    promoted, _ = users.update_user(conn, actor_user_id=boss, user_id=viewer, role="admin")
    assert promoted["account_ids"] == _ids(conn)
    trimmed, _ = users.update_user(conn, actor_user_id=boss, user_id=viewer, account_ids=[])
    assert trimmed["account_ids"] == _ids(conn)                     # cannot be narrowed while admin
    demoted, _ = users.update_user(conn, actor_user_id=boss, user_id=viewer, role="viewer", account_ids=_ids(conn)[:2])
    assert demoted["account_ids"] == _ids(conn)[:2]
