"""
INC-10 -- shared fixtures for tests/persistence/*. A temp SQLite file per
test (never a shared/module-scoped DB) so tests can never interfere with
each other's state.
"""

import sqlite3
from pathlib import Path

import pytest

from mcma.persistence.db import open_database


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "mcma_test.sqlite3"


@pytest.fixture()
def conn(db_path: Path) -> sqlite3.Connection:
    connection = open_database(db_path)
    yield connection
    connection.close()


def seed_account(
    conn: sqlite3.Connection, account_id: str = "acct-1", *, entity: str = "MAMDA", scope: str = "OUJDA"
) -> None:
    """Correction batch: accounts now enforce UNIQUE(entity, scope) (one
    row per shared PortalAccount profile) -- a test that seeds a SECOND
    account in the same test must pass a distinct entity/scope pair, never
    rely on the default twice."""
    conn.execute(
        "INSERT INTO accounts (account_id, label, entity, scope, active, created_at) "
        "VALUES (?, 'Test Account', ?, ?, 1, '2026-01-01T00:00:00+00:00')",
        (account_id, entity, scope),
    )


def seed_user(conn: sqlite3.Connection, user_id: str = "user-1") -> None:
    conn.execute(
        "INSERT INTO users (user_id, username, password_hash, role, active) VALUES (?, ?, 'hash', 'admin', 1)",
        (user_id, f"{user_id}-username"),
    )
