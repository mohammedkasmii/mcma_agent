"""INC-11 -- mcma.execution.lease threads a real AccountLeaseHandle."""

import asyncio
from pathlib import Path

from mcma.execution.lease import acquire_account_lease, new_instance_id
from mcma.persistence.db import open_database


def run_async(coro):
    return asyncio.run(coro)


def test_acquire_account_lease_returns_a_valid_handle(tmp_path: Path):
    conn = open_database(tmp_path / "mcma.sqlite3")
    conn.execute(
        "INSERT INTO accounts (account_id, label, entity, scope, active, created_at) "
        "VALUES ('acct-1', 'L', 'MAMDA', 'OUJDA', 1, '2026-01-01T00:00:00+00:00')"
    )
    instance_id = new_instance_id()
    handle = acquire_account_lease(conn, "acct-1", instance_id)
    assert handle.account_id == "acct-1"
    run_async(handle.assert_valid())
    conn.close()


def test_new_instance_id_is_stable_and_unique():
    a = new_instance_id()
    b = new_instance_id()
    assert a != b
    assert isinstance(a, str) and a
