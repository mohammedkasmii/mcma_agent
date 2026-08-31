"""INC-15 -- shared fixtures/stubs for tests/app/sse/*."""

import sqlite3
from pathlib import Path

import pytest

from mcma.persistence.db import open_database
from mcma.persistence.repositories.outbox import AccountStateVersionRepository, EventOutboxRepository

ACCOUNT_A = "acct-a"
ACCOUNT_B = "acct-b"


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "mcma_test.sqlite3"


@pytest.fixture()
def conn(db_path: Path) -> sqlite3.Connection:
    connection = open_database(db_path)
    for account_id in (ACCOUNT_A, ACCOUNT_B):
        connection.execute(
            "INSERT INTO accounts (account_id, label, entity, scope, active, created_at) "
            "VALUES (?, ?, 'MAMDA', 'OUJDA', 1, '2026-01-01T00:00:00+00:00')",
            (account_id, account_id),
        )
    yield connection
    connection.close()


def emit_event(conn, account_id: str, event_type: str = "TEST_EVENT", created_at: str = "2026-01-01T00:00:00+00:00") -> int:
    version = AccountStateVersionRepository(conn).bump(account_id)
    return EventOutboxRepository(conn).insert(account_id, version, "test", event_type, "{}", created_at)


class StubAuthorizer:
    def __init__(self, visible: set, authorized: bool = True):
        self._visible = visible
        self._authorized = authorized

    def visible_accounts(self, principal):
        return set(self._visible)

    def is_authorized(self, principal, account_id: str) -> bool:
        return self._authorized and account_id in self._visible

    def revoke(self):
        self._authorized = False
