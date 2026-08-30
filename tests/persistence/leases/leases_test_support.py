"""
INC-11 -- shared fixtures/helpers for tests/persistence/leases/*.
Deliberately self-contained (duplicates the tiny db_path/conn/seed_account
helpers from tests/persistence/persistence_test_support.py) rather than
reaching across a test directory boundary via sys.path -- this project's
established bounded-duplication convention (see that module's own
docstring and every tests/portal/*/*_test_support.py file).
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


def seed_account(conn: sqlite3.Connection, account_id: str = "acct-1") -> None:
    conn.execute(
        "INSERT INTO accounts (account_id, label, entity, scope, active, created_at) "
        "VALUES (?, 'Test Account', 'MAMDA', 'OUJDA', 1, '2026-01-01T00:00:00+00:00')",
        (account_id,),
    )
