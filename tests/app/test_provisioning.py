"""Pilot-integration correction (section 2) -- safe, idempotent account
provisioning and user-access assignment: never duplicates a canonical
profile, adding an employee never creates a new portal account."""

import pytest

from mcma.domain.portal_accounts import PortalAccountProfile, canonical_account_id
from mcma.persistence.db import open_database
from mcma.app.provisioning import ensure_canonical_accounts, grant_user_access


@pytest.fixture()
def conn(tmp_path):
    connection = open_database(tmp_path / "mcma_test.sqlite3")
    yield connection
    connection.close()


def test_ensure_canonical_accounts_creates_exactly_four(conn):
    result = ensure_canonical_accounts(conn)
    assert len(result) == 4
    assert set(result.values()) == {"created"}
    count = conn.execute("SELECT COUNT(*) AS c FROM accounts").fetchone()["c"]
    assert count == 4


def test_ensure_canonical_accounts_is_idempotent(conn):
    ensure_canonical_accounts(conn)
    second = ensure_canonical_accounts(conn)
    assert set(second.values()) == {"already_existed"}
    count = conn.execute("SELECT COUNT(*) AS c FROM accounts").fetchone()["c"]
    assert count == 4  # never duplicated


def test_adding_an_employee_never_creates_a_new_portal_account(conn):
    ensure_canonical_accounts(conn)
    before = conn.execute("SELECT COUNT(*) AS c FROM accounts").fetchone()["c"]

    conn.execute(
        "INSERT INTO users (user_id, username, password_hash, role, active) VALUES ('u1', 'alice', 'h', 'operator', 1)"
    )
    grant_user_access(conn, "u1", PortalAccountProfile.from_row("MCMA", "OUJDA"))

    after = conn.execute("SELECT COUNT(*) AS c FROM accounts").fetchone()["c"]
    assert after == before  # no new account row was created

    access = conn.execute(
        "SELECT account_id FROM user_account_access WHERE user_id='u1'"
    ).fetchall()
    assert {r["account_id"] for r in access} == {canonical_account_id(PortalAccountProfile.from_row("MCMA", "OUJDA"))}


def test_multiple_users_can_reference_the_same_portal_account(conn):
    ensure_canonical_accounts(conn)
    conn.execute("INSERT INTO users (user_id, username, password_hash, role, active) VALUES ('u1','a','h','operator',1)")
    conn.execute("INSERT INTO users (user_id, username, password_hash, role, active) VALUES ('u2','b','h','operator',1)")
    profile = PortalAccountProfile.from_row("MCMA", "OUJDA")
    grant_user_access(conn, "u1", profile)
    grant_user_access(conn, "u2", profile)

    count = conn.execute(
        "SELECT COUNT(*) AS c FROM accounts WHERE account_id=?", (canonical_account_id(profile),)
    ).fetchone()["c"]
    assert count == 1  # still exactly one shared account row for two users


def test_grant_fails_closed_when_account_row_is_missing(conn):
    conn.execute("INSERT INTO users (user_id, username, password_hash, role, active) VALUES ('u1','a','h','operator',1)")
    with pytest.raises(ValueError):
        grant_user_access(conn, "u1", PortalAccountProfile.from_row("MCMA", "OUJDA"))
