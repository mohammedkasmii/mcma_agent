"""Shared fixtures/helpers for tests/app/runners/* (Phase 1C-A: workstation
job-dispatch control plane). Mirrors tests/persistence/persistence_test_support.py
and tests/app/api/api_test_support.py's conventions: one temp SQLite file per
test, synthetic data only."""

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pytest

from mcma.app.auth.passwords import hash_password
from mcma.app.runners.registry import RunnerPrincipal
from mcma.execution.inputs import TestOnlyPlaintextEncryptor, compute_content_hash
from mcma.persistence.db import open_database
from mcma.persistence.repositories.jobs import AutomationJobsRepository, JobInputsRepository

OUJDA = "acct-mcma-oujda"
NADOR = "acct-mcma-nador"
MAMDA_OUJDA = "acct-mamda-oujda"
MAMDA_NADOR = "acct-mamda-nador"


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "mcma_test.sqlite3"


@pytest.fixture()
def conn(db_path: Path) -> sqlite3.Connection:
    connection = open_database(db_path)
    for account_id, entity, scope in (
        (OUJDA, "MCMA", "OUJDA"), (NADOR, "MCMA", "NADOR"),
        (MAMDA_OUJDA, "MAMDA", "OUJDA"), (MAMDA_NADOR, "MAMDA", "NADOR"),
    ):
        connection.execute(
            "INSERT INTO accounts (account_id, label, entity, scope, active, created_at) "
            "VALUES (?, ?, ?, ?, 1, '2026-01-01T00:00:00+00:00')",
            (account_id, account_id, entity, scope),
        )
    yield connection
    connection.close()


@pytest.fixture()
def encryptor() -> TestOnlyPlaintextEncryptor:
    return TestOnlyPlaintextEncryptor()


def create_user(conn, username: Optional[str] = None, *, role: str = "operator", active: bool = True) -> str:
    user_id = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO users (user_id, username, password_hash, role, active) VALUES (?, ?, ?, ?, ?)",
        (user_id, username or f"user-{user_id}", hash_password("correct horse battery"), role, 1 if active else 0),
    )
    return user_id


def grant_access(conn, user_id: str, account_id: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO user_account_access (user_id, account_id, granted_at) VALUES (?, ?, ?)",
        (user_id, account_id, "2026-01-01T00:00:00+00:00"),
    )


def revoke_access(conn, user_id: str, account_id: str) -> None:
    conn.execute("DELETE FROM user_account_access WHERE user_id = ? AND account_id = ?", (user_id, account_id))


def create_runner(
    conn, user_id: str, *, runner_id: Optional[str] = None, status: str = "ACTIVE",
    last_seen_at: Optional[str] = "2026-01-01T00:00:00+00:00",
) -> str:
    runner_id = runner_id or uuid.uuid4().hex
    enrollment_id = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO runner_enrollments (enrollment_id, code_digest, target_user_id, created_by_user_id, "
        "created_at, expires_at, consumed_at) VALUES (?, ?, ?, ?, '2026-01-01T00:00:00+00:00', "
        "'2026-01-02T00:00:00+00:00', '2026-01-01T00:00:00+00:00')",
        (enrollment_id, uuid.uuid4().hex.ljust(64, "0")[:64], user_id, user_id),
    )
    revoked_at = None if status == "ACTIVE" else "2026-01-01T00:00:00+00:00"
    conn.execute(
        "INSERT INTO runners (runner_id, user_id, credential_digest, runner_label, status, enrollment_id, "
        "created_at, last_seen_at, revoked_at) VALUES (?, ?, ?, 'Test Runner', ?, ?, "
        "'2026-01-01T00:00:00+00:00', ?, ?)",
        (runner_id, user_id, uuid.uuid4().hex.ljust(64, "1")[:64], status, enrollment_id, last_seen_at, revoked_at),
    )
    return runner_id


def set_ready(conn, runner_id: str, account_id: str, *, state: str = "READY") -> None:
    conn.execute(
        "INSERT INTO runner_account_capabilities (runner_id, account_id, session_state, updated_at) "
        "VALUES (?, ?, ?, '2026-01-01T00:00:00+00:00') "
        "ON CONFLICT(runner_id, account_id) DO UPDATE SET session_state = excluded.session_state",
        (runner_id, account_id, state),
    )


def principal(conn, runner_id: str) -> RunnerPrincipal:
    row = conn.execute("SELECT user_id FROM runners WHERE runner_id = ?", (runner_id,)).fetchone()
    return RunnerPrincipal(runner_id=runner_id, user_id=row["user_id"])


def create_job(
    conn, job_id: str, *, account_id: str, user_id: str, mode: str = "DRY_RUN", status: str = "QUEUED",
    workflow_name: str = "RENOUVELLEMENT_CONTRAT", created_at: str = "2026-01-01T00:00:00+00:00",
    typed_input: object = None, encryptor: Optional[TestOnlyPlaintextEncryptor] = None,
    raw_payload: Optional[bytes] = None,
) -> None:
    """Seeds a job directly (dispatch tests may seed jobs directly, per the
    task spec) along with its verifiable job_inputs row -- unless
    typed_input=False, in which case NO job_inputs row is created at all
    (used to exercise the MissingJobInput fail-closed path). `raw_payload`,
    when given, is stored as-is (bypassing json.dumps(typed_input)
    entirely) -- used to seed malformed/deeply-recursive raw JSON TEXT that
    a real client could never have produced from a dict."""
    import json

    if raw_payload is not None:
        payload = raw_payload
    else:
        payload = json.dumps(typed_input if typed_input is not None else {"claim_id": "C-1"}, sort_keys=True).encode("utf-8")
    content_hash = compute_content_hash(payload)
    AutomationJobsRepository(conn).insert(
        job_id=job_id, account_id=account_id, requested_by_user_id=user_id, workflow_name=workflow_name,
        mode=mode, status=status, input_hash=content_hash, idempotency_key=job_id, created_at=created_at,
        state_version=1,
    )
    if typed_input is not False:  # False is the explicit "no input row at all" sentinel
        enc = encryptor or TestOnlyPlaintextEncryptor()
        JobInputsRepository(conn).insert(
            job_id, content_hash, enc.encrypt(payload), "CLAIM_DATA", created_at, "2027-01-01T00:00:00+00:00",
        )


def utc(text: str) -> datetime:
    return datetime.fromisoformat(text).astimezone(timezone.utc)
