"""INC-16 -- shared fixtures for tests/app/auth/*."""

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
