"""INC-17 -- shared fixtures/helpers for tests/app/api/*."""

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mcma.app.api.app import create_api_app
from mcma.app.auth.passwords import hash_password
from mcma.app.auth.provider import LocalUserAuthProvider
from mcma.app.auth.sessions import SessionStore
from mcma.execution.inputs import TestOnlyPlaintextEncryptor
from mcma.persistence.db import open_database

OUJDA = "acct-mcma-oujda"
NADOR = "acct-mcma-nador"
MAMDA_OUJDA = "acct-mamda-oujda"
MAMDA_NADOR = "acct-mamda-nador"


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "mcma_test.sqlite3"


@pytest.fixture()
def conn(db_path: Path) -> sqlite3.Connection:
    """OUJDA/NADOR are the two MCMA (write-capable) shared PortalAccount
    profiles the job-creation/authz tests exercise. MAMDA_OUJDA/MAMDA_NADOR
    are the two notification-only profiles the MAMDA-enforcement tests use
    -- all four coexist under the (entity, scope) uniqueness constraint
    (correction batch) because MCMA/OUJDA != MAMDA/OUJDA."""
    connection = open_database(db_path)
    for account_id, entity, scope in (
        (OUJDA, "MCMA", "OUJDA"),
        (NADOR, "MCMA", "NADOR"),
        (MAMDA_OUJDA, "MAMDA", "OUJDA"),
        (MAMDA_NADOR, "MAMDA", "NADOR"),
    ):
        connection.execute(
            "INSERT INTO accounts (account_id, label, entity, scope, active, created_at) "
            "VALUES (?, ?, ?, ?, 1, '2026-01-01T00:00:00+00:00')",
            (account_id, account_id, entity, scope),
        )
    yield connection
    connection.close()


def create_user(conn, username: str, password: str, role: str) -> str:
    user_id = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO users (user_id, username, password_hash, role, active) VALUES (?, ?, ?, ?, 1)",
        (user_id, username, hash_password(password), role),
    )
    return user_id


def grant_access(conn, user_id: str, account_id: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO user_account_access (user_id, account_id, granted_at) VALUES (?, ?, ?)",
        (user_id, account_id, datetime.now(timezone.utc).isoformat()),
    )


@pytest.fixture()
def app_and_client(conn):
    session_store = SessionStore()
    app = create_api_app(
        conn,
        auth_provider=LocalUserAuthProvider(conn),
        session_store=session_store,
        encryptor=TestOnlyPlaintextEncryptor(),
        secure_cookies=False,
    )
    client = TestClient(app, client=("127.0.0.1", 12345))
    return app, client, session_store


def login_client(client, username: str, password: str) -> str:
    """Logs in and returns the CSRF token to use on subsequent
    state-changing requests (the client's own cookie jar already holds
    the session AND csrf cookies after this call)."""
    response = client.post("/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["csrf_token"]


def csrf_headers(csrf_token: str) -> dict:
    return {"X-CSRF-Token": csrf_token}
