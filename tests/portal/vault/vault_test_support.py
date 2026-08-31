"""INC-13 -- shared fixtures/stubs for tests/portal/vault/*."""

import sqlite3
from pathlib import Path

import pytest

from mcma.persistence.db import open_database
from mcma.portal.vault import TestOnlyAclVerifier, TestOnlyInMemoryCryptoBackend

ACCOUNT_ID = "acct-1"


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "mcma_test.sqlite3"


@pytest.fixture()
def conn(db_path: Path) -> sqlite3.Connection:
    connection = open_database(db_path)
    connection.execute(
        "INSERT INTO accounts (account_id, label, entity, scope, active, created_at) "
        "VALUES (?, 'Test', 'MAMDA', 'OUJDA', 1, '2026-01-01T00:00:00+00:00')",
        (ACCOUNT_ID,),
    )
    yield connection
    connection.close()


@pytest.fixture()
def vault_dir(tmp_path: Path) -> Path:
    d = tmp_path / "vault"
    d.mkdir()
    return d


@pytest.fixture()
def backend() -> TestOnlyInMemoryCryptoBackend:
    return TestOnlyInMemoryCryptoBackend()


@pytest.fixture()
def restrictive_acl() -> TestOnlyAclVerifier:
    return TestOnlyAclVerifier(True)


@pytest.fixture()
def permissive_acl() -> TestOnlyAclVerifier:
    return TestOnlyAclVerifier(False)


class SyntheticLeaseHandle:
    def __init__(self, account_id: str, valid: bool = True):
        self.account_id = account_id
        self.valid = valid

    async def assert_valid(self) -> None:
        if not self.valid:
            raise RuntimeError(f"lease for {self.account_id} is not valid")
