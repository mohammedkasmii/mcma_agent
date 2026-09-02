"""
The category foreign key, exercised against a real SQLite database.

poll_run_categories.category_code references categories(code_alerte), and
the categories table ships empty because there is no reviewed fixed list
of alert codes anywhere in this repository -- they are whatever the
account's portal currently offers. Onsite, discovery succeeded, the reads
succeeded, and the run then died on an IntegrityError while recording
what it had just read.

These tests use the real schema and a real connection. The portal is
faked; the database is not, because the ordering under test is enforced
by the database.
"""

from __future__ import annotations

import asyncio
import sqlite3

import pytest

from mcma.notifications import poller as poller_module
from mcma.persistence.db import open_database


ACCOUNT = "acct-test-1"
DISCOVERED = "CODE-X"


class _FakeReader:
    """Answers one synthetic notification row for whatever code it is
    asked for, and records the order of calls."""

    def __init__(self, log):
        self._log = log

    async def discover_notification_categories(self):
        self._log.append("discover")
        return (DISCOVERED,)

    async def observe_session_state(self):
        return "AUTHENTICATED"

    async def read_notifications(self, code_alerte):
        self._log.append(f"read:{code_alerte}")
        return (
            {
                "IdSinistre": "900001",
                "ReferenceCie": "<b>REF-TEST-1</b>",
                "NomSocietaire": "Societaire Test",
                "Police": "POL-TEST-1",
                "Matricule": "0000-A-0",
            },
        )

    async def close(self):
        return None


class _FakeLease:
    def release(self):
        return None

    async def assert_valid(self):
        return None


@pytest.fixture()
def conn(tmp_path):
    connection = open_database(tmp_path / "categories.sqlite3")
    connection.execute(
        "INSERT INTO accounts (account_id, label, entity, scope, active, created_at) "
        "VALUES (?, 'Compte de test', 'MCMA', 'ZONE-A', 1, '2026-01-01T00:00:00+00:00')",
        (ACCOUNT,),
    )
    yield connection
    connection.close()


def _run_poll_with_fakes(conn, monkeypatch, log):
    reader = _FakeReader(log)

    async def fake_open_reader(*args, **kwargs):
        return reader

    monkeypatch.setattr(poller_module, "open_reader", fake_open_reader)
    monkeypatch.setattr(poller_module, "acquire_lease", lambda *a, **k: _FakeLease())
    monkeypatch.setattr(
        poller_module, "load_and_verify_session", lambda *a, **k: '{"cookies": []}'
    )
    monkeypatch.setattr(
        poller_module, "category_discovery_contracts", lambda *a, **k: ()
    )
    monkeypatch.setattr(poller_module, "notification_contracts", lambda *a, **k: ())

    # A real CategoriesRepository, wrapped only to record when it ran
    # relative to the FK-dependent insert.
    real_repository = poller_module.CategoriesRepository

    class _RecordingCategories(real_repository):
        def ensure(self, code_alerte, label):
            log.append(f"categories.ensure:{code_alerte}")
            return super().ensure(code_alerte, label)

    monkeypatch.setattr(poller_module, "CategoriesRepository", _RecordingCategories)

    return asyncio.run(
        poller_module.poll_one_account(
            conn,
            object(),
            ACCOUNT,
            (),
            instance_id="instance-1",
            allowed_host="portal.test",
            vault_dir=None,
            crypto_backend=None,
            entity="MCMA",
        )
    )


def test_the_discovered_code_is_absent_before_the_poll(conn):
    rows = conn.execute(
        "SELECT code_alerte FROM categories WHERE code_alerte = ?", (DISCOVERED,)
    ).fetchall()
    assert rows == []


def test_polling_registers_the_discovered_category_and_records_the_run(conn, monkeypatch):
    log: list[str] = []
    outcome = _run_poll_with_fakes(conn, monkeypatch, log)

    assert outcome == "POLLED"

    # The code now exists as a category...
    category = conn.execute(
        "SELECT code_alerte, label FROM categories WHERE code_alerte = ?", (DISCOVERED,)
    ).fetchone()
    assert category is not None
    assert category["code_alerte"] == DISCOVERED

    # ...and the FK-dependent row was accepted by the database.
    poll_rows = conn.execute(
        "SELECT category_code, status FROM poll_run_categories WHERE category_code = ?",
        (DISCOVERED,),
    ).fetchall()
    assert len(poll_rows) == 1
    assert poll_rows[0]["status"] == "COMPLETE"


def test_registration_happens_before_the_foreign_key_dependent_insert(conn, monkeypatch):
    log: list[str] = []
    _run_poll_with_fakes(conn, monkeypatch, log)

    ensure_index = log.index(f"categories.ensure:{DISCOVERED}")
    read_index = log.index(f"read:{DISCOVERED}")
    # Registered before the reads that produce the poll_run_categories row.
    assert ensure_index < read_index


def test_no_integrity_error_escapes_the_poll(conn, monkeypatch):
    """The onsite failure mode: discovery and reads both succeed, then the
    run dies recording what it read."""
    log: list[str] = []
    try:
        outcome = _run_poll_with_fakes(conn, monkeypatch, log)
    except sqlite3.IntegrityError as exc:  # pragma: no cover - the regression
        pytest.fail(f"the poll raised an IntegrityError: {exc}")
    assert outcome == "POLLED"


def test_the_real_row_reaches_claims_rather_than_unmatched(conn, monkeypatch):
    """The other half of the same trip: a portal-shaped row must arrive in
    claims, not in unmatched_notifications."""
    _run_poll_with_fakes(conn, monkeypatch, [])

    claim = conn.execute(
        "SELECT reference, insured, police, matricule_norm FROM claims WHERE account_id = ?",
        (ACCOUNT,),
    ).fetchone()
    assert claim is not None
    assert claim["reference"] == "REF-TEST-1"
    assert claim["insured"] == "Societaire Test"
    assert claim["matricule_norm"] == "0000-A-0"

    unmatched = conn.execute(
        "SELECT COUNT(*) AS n FROM unmatched_notifications WHERE account_id = ?", (ACCOUNT,)
    ).fetchone()
    assert unmatched["n"] == 0


def test_one_account_poll_touches_only_its_own_rows(conn, monkeypatch):
    """Account isolation, exercised rather than asserted about: a second
    account exists and must be untouched by the first account's poll."""
    conn.execute(
        "INSERT INTO accounts (account_id, label, entity, scope, active, created_at) "
        "VALUES ('acct-test-2', 'Autre compte', 'MAMDA', 'ZONE-B', 1, '2026-01-01T00:00:00+00:00')"
    )
    _run_poll_with_fakes(conn, monkeypatch, [])

    other_claims = conn.execute(
        "SELECT COUNT(*) AS n FROM claims WHERE account_id = 'acct-test-2'"
    ).fetchone()
    other_polls = conn.execute(
        "SELECT COUNT(*) AS n FROM poll_runs WHERE account_id = 'acct-test-2'"
    ).fetchone()
    assert other_claims["n"] == 0
    assert other_polls["n"] == 0


def test_a_malformed_configured_code_never_reaches_the_portal(conn, monkeypatch):
    """A configured code is validated exactly like a discovered one."""
    log: list[str] = []
    reader = _FakeReader(log)

    async def fake_open_reader(*args, **kwargs):
        return reader

    monkeypatch.setattr(poller_module, "open_reader", fake_open_reader)
    monkeypatch.setattr(poller_module, "acquire_lease", lambda *a, **k: _FakeLease())
    monkeypatch.setattr(
        poller_module, "load_and_verify_session", lambda *a, **k: '{"cookies": []}'
    )
    monkeypatch.setattr(poller_module, "category_discovery_contracts", lambda *a, **k: ())
    monkeypatch.setattr(poller_module, "notification_contracts", lambda *a, **k: ())

    asyncio.run(
        poller_module.poll_one_account(
            conn,
            object(),
            ACCOUNT,
            ("../evil", "code/../.."),
            instance_id="instance-1",
            allowed_host="portal.test",
            vault_dir=None,
            crypto_backend=None,
            entity="MCMA",
        )
    )

    # Both configured values were dropped, so the poller fell through to
    # discovery rather than fetching either one.
    assert "read:../evil" not in log
    assert "read:code/../.." not in log
