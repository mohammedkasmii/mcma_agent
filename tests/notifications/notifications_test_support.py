"""INC-14 -- shared fixtures/stubs for tests/notifications/*."""

import sqlite3
from pathlib import Path

import pytest

from mcma.persistence.db import open_database
from mcma.persistence.repositories.claims import CategoriesRepository, ClaimsRepository, PollRunsRepository

OUJDA = "acct-oujda"
NADOR = "acct-nador"
CATEGORY = "CAT_SIN"


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "mcma_test.sqlite3"


@pytest.fixture()
def conn(db_path: Path) -> sqlite3.Connection:
    connection = open_database(db_path)
    for account_id, scope in ((OUJDA, "OUJDA"), (NADOR, "NADOR")):
        connection.execute(
            "INSERT INTO accounts (account_id, label, entity, scope, active, created_at) "
            "VALUES (?, ?, 'MAMDA', ?, 1, '2026-01-01T00:00:00+00:00')",
            (account_id, account_id, scope),
        )
    CategoriesRepository(connection).ensure(CATEGORY, "Sinistre notifications")
    yield connection
    connection.close()


def seed_claim(conn: sqlite3.Connection, account_id: str, claim_pk: str, portal_claim_id: str, version: int = 1) -> str:
    return ClaimsRepository(conn).upsert(claim_pk, account_id, portal_claim_id, version)


def new_poll_run(conn: sqlite3.Connection, account_id: str, poll_run_id: str, status: str = "COMPLETE") -> None:
    PollRunsRepository(conn).create(poll_run_id, account_id, "2026-01-01T00:00:00+00:00", status, session_valid=True)


class StubReader:
    """Duck-types the ONE method mcma.notifications.extract needs from
    ReadCapability -- structurally incapable of writing (no other method
    exists on it at all)."""

    def __init__(self, results: dict):
        # results: {category_code: rows_or_Exception}
        self._results = results
        self.calls = []

    async def read_notifications(self, code_alerte: str):
        self.calls.append(code_alerte)
        outcome = self._results.get(code_alerte, ())
        if isinstance(outcome, Exception):
            raise outcome
        return outcome
