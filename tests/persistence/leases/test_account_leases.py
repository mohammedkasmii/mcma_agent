"""
INC-11 -- account_leases acquire/renew/expire, heartbeat-loss aborts a
stub write context, and the fencing token is documented/structurally
internal-only.
"""

from datetime import datetime, timedelta, timezone

import pytest

from mcma.persistence.leases import (
    AccountLeaseHandle,
    LeaseInvalid,
    LeaseNotHeld,
    acquire_lease,
    release_stale_leases,
)
from leases_test_support import seed_account


def run_async(coro):
    import asyncio

    return asyncio.run(coro)


def test_lease_acquire_renew_expire(conn):
    seed_account(conn)
    handle = acquire_lease(conn, "acct-1", "instance-1", ttl_seconds=60)
    run_async(handle.assert_valid())  # must not raise

    handle.heartbeat()
    run_async(handle.assert_valid())  # still valid after renew

    # A second acquire attempt while unexpired is rejected.
    with pytest.raises(LeaseNotHeld):
        acquire_lease(conn, "acct-1", "instance-2", ttl_seconds=60)

    # Simulate expiry by rewriting expires_at directly, then a new owner
    # can acquire (an expired lease frees the account).
    past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    conn.execute("UPDATE account_leases SET expires_at = ? WHERE account_id = 'acct-1'", (past,))
    with pytest.raises(LeaseInvalid):
        run_async(handle.assert_valid())

    new_handle = acquire_lease(conn, "acct-1", "instance-2", ttl_seconds=60)
    run_async(new_handle.assert_valid())


def test_lease_replaced_by_another_owner_invalidates_the_old_handle(conn):
    seed_account(conn)
    original = acquire_lease(conn, "acct-1", "instance-1", ttl_seconds=1)
    past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    conn.execute("UPDATE account_leases SET expires_at = ? WHERE account_id = 'acct-1'", (past,))
    acquire_lease(conn, "acct-1", "instance-2", ttl_seconds=60)  # replaces the row

    with pytest.raises(LeaseInvalid):
        run_async(original.assert_valid())
    with pytest.raises(LeaseInvalid):
        original.heartbeat()


def test_release_then_reacquire_by_a_new_owner(conn):
    seed_account(conn)
    handle = acquire_lease(conn, "acct-1", "instance-1")
    handle.release()
    new_handle = acquire_lease(conn, "acct-1", "instance-2")
    run_async(new_handle.assert_valid())


def test_release_stale_leases_removes_only_expired_rows(conn):
    seed_account(conn, "acct-1")
    seed_account(conn, "acct-2", scope="NADOR")
    acquire_lease(conn, "acct-2", "instance-1", ttl_seconds=3600)  # fresh, not stale
    acquire_lease(conn, "acct-1", "instance-1", ttl_seconds=60)
    past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    conn.execute("UPDATE account_leases SET expires_at = ? WHERE account_id = 'acct-1'", (past,))

    removed = release_stale_leases(conn)
    assert removed == 1
    remaining = conn.execute("SELECT account_id FROM account_leases").fetchall()
    assert {r["account_id"] for r in remaining} == {"acct-2"}


# --------------------------------------------------------------------- #
# Heartbeat-loss aborts routing and closes the write context -- proven
# against a stub write context standing in for VerifiedMissionWriter's
# already-established _preflight_before_mutation/_terminal_abort contract.
# --------------------------------------------------------------------- #


class _StubWriteContext:
    """Mirrors the exact contract mcma.portal.writer.VerifiedMissionWriter
    already implements: recheck the stored lease immediately before every
    request-emitting action; on LeaseInvalid, abort routing and close."""

    def __init__(self, lease_handle):
        self._lease_handle = lease_handle
        self.aborted = False
        self.closed = False

    async def add_row(self):
        try:
            await self._lease_handle.assert_valid()
        except LeaseInvalid:
            self.aborted = True
            self.closed = True
            raise
        return "row-written"


def test_heartbeat_loss_aborts_routing_and_closes_write_context(conn):
    seed_account(conn)
    handle = acquire_lease(conn, "acct-1", "instance-1", ttl_seconds=60)
    write_context = _StubWriteContext(handle)

    assert run_async(write_context.add_row()) == "row-written"
    assert write_context.aborted is False

    # Heartbeat loss: another owner acquires after this one's lease expires.
    past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    conn.execute("UPDATE account_leases SET expires_at = ? WHERE account_id = 'acct-1'", (past,))
    acquire_lease(conn, "acct-1", "instance-2", ttl_seconds=60)

    with pytest.raises(LeaseInvalid):
        run_async(write_context.add_row())
    assert write_context.aborted is True
    assert write_context.closed is True


def test_fencing_token_is_internal_only(conn):
    """The fencing token never appears in any method whose name suggests
    portal/network interaction -- AccountLeaseHandle's only public methods
    are assert_valid/heartbeat/release, all pure-DB operations."""
    seed_account(conn)
    handle = acquire_lease(conn, "acct-1", "instance-1")
    public_methods = {name for name in dir(handle) if not name.startswith("_") and callable(getattr(handle, name))}
    assert public_methods == {"assert_valid", "heartbeat", "release"}
    assert "internal" in (AccountLeaseHandle.__doc__ or "").lower()
