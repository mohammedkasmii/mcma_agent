"""
mcma.persistence.leases -- per-account exclusive leases (INC-11,
ADR-0007, DATA_MODEL.md §5, SAFETY_MODEL.md §5).

`AccountLeaseHandle` structurally satisfies mcma.portal.capabilities.
LeaseHandle (a Protocol: `account_id: str` + `async assert_valid()`) --
duck-typed, no import of mcma.portal here (persistence and portal are
sibling layers; neither may import the other). The `fencing_token` is an
INTERNAL guard only: SinAuto never sees or validates it (DATA_MODEL.md
§5's fencing caveat) -- it exists solely so THIS process can detect that
its own lease was lost or replaced and stop. Nothing in this module ever
sends the token anywhere near a portal request.

Acquire is atomic: an INSERT for a never-held account, or an UPDATE only
when the existing row's `expires_at` has already passed -- wrapped in one
BEGIN IMMEDIATE/COMMIT so a concurrent acquire attempt on the same
account cannot race between the expiry check and the write.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

DEFAULT_LEASE_TTL_SECONDS = 60


class LeaseInvalid(Exception):
    """Raised by assert_valid()/heartbeat() when the lease is no longer
    held by this handle -- lost, replaced, or expired."""

    def __init__(self, account_id: str) -> None:
        super().__init__(f"lease for account {account_id!r} is not valid")
        self.account_id = account_id


class LeaseNotHeld(Exception):
    """Raised by acquire_lease() when another (unexpired) holder already
    owns the account's lease."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _parse(iso: str) -> datetime:
    return datetime.fromisoformat(iso)


class AccountLeaseHandle:
    """Structurally a LeaseHandle (account_id + async assert_valid()).
    Also offers heartbeat()/release() for the holder's own lifecycle
    management -- neither is part of the LeaseHandle protocol portal
    capabilities consume, since portal never manages lease lifetime, only
    checks validity. The fencing token this handle carries is an INTERNAL
    guard only (DATA_MODEL.md §5) -- never sent to, or validated by, the
    portal."""

    def __init__(self, conn: sqlite3.Connection, account_id: str, fencing_token: str, ttl_seconds: int) -> None:
        self._conn = conn
        self.account_id = account_id
        self._fencing_token = fencing_token
        self._ttl_seconds = ttl_seconds
        self._released = False

    async def assert_valid(self) -> None:
        if self._released:
            raise LeaseInvalid(self.account_id)
        row = self._conn.execute(
            "SELECT fencing_token, expires_at FROM account_leases WHERE account_id = ?", (self.account_id,)
        ).fetchone()
        if row is None or row["fencing_token"] != self._fencing_token:
            raise LeaseInvalid(self.account_id)
        if _parse(row["expires_at"]) < _utcnow():
            raise LeaseInvalid(self.account_id)

    def heartbeat(self) -> None:
        """Renews heartbeat_at/expires_at. Raises LeaseInvalid if this
        handle no longer owns the row (lost/replaced) -- never silently
        re-acquires."""
        now = _utcnow()
        expires_at = now + timedelta(seconds=self._ttl_seconds)
        cursor = self._conn.execute(
            "UPDATE account_leases SET heartbeat_at = ?, expires_at = ? WHERE account_id = ? AND fencing_token = ?",
            (_iso(now), _iso(expires_at), self.account_id, self._fencing_token),
        )
        if cursor.rowcount == 0:
            raise LeaseInvalid(self.account_id)

    def release(self) -> None:
        """Idempotent. Releases the row only if this handle still owns
        it (a lease already lost/replaced is simply left alone -- this
        handle has nothing valid left to release)."""
        if self._released:
            return
        self._conn.execute(
            "DELETE FROM account_leases WHERE account_id = ? AND fencing_token = ?",
            (self.account_id, self._fencing_token),
        )
        self._released = True


def acquire_lease(
    conn: sqlite3.Connection,
    account_id: str,
    owner_instance_id: str,
    *,
    owner_job_id: Optional[str] = None,
    ttl_seconds: int = DEFAULT_LEASE_TTL_SECONDS,
) -> AccountLeaseHandle:
    now = _utcnow()
    expires_at = now + timedelta(seconds=ttl_seconds)
    fencing_token = uuid.uuid4().hex

    conn.execute("BEGIN IMMEDIATE")
    try:
        cursor = conn.execute(
            "UPDATE account_leases SET owner_instance_id=?, owner_job_id=?, fencing_token=?, "
            "acquired_at=?, heartbeat_at=?, expires_at=? WHERE account_id=? AND expires_at < ?",
            (
                owner_instance_id,
                owner_job_id,
                fencing_token,
                _iso(now),
                _iso(now),
                _iso(expires_at),
                account_id,
                _iso(now),
            ),
        )
        if cursor.rowcount == 0:
            try:
                conn.execute(
                    "INSERT INTO account_leases (account_id, owner_instance_id, owner_job_id, fencing_token, "
                    "acquired_at, heartbeat_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (account_id, owner_instance_id, owner_job_id, fencing_token, _iso(now), _iso(now), _iso(expires_at)),
                )
            except sqlite3.IntegrityError:
                conn.execute("ROLLBACK")
                raise LeaseNotHeld(f"account {account_id!r} lease is currently held by another owner")
        conn.execute("COMMIT")
    except LeaseNotHeld:
        raise
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return AccountLeaseHandle(conn, account_id, fencing_token, ttl_seconds)


def release_stale_leases(conn: sqlite3.Connection) -> int:
    """Used by restart reconciliation (INC-12, WORKFLOW_STATE_MODEL.md §7's
    'stale account_leases released first'). Returns the number released."""
    now = _utcnow()
    cursor = conn.execute("DELETE FROM account_leases WHERE expires_at < ?", (_iso(now),))
    return cursor.rowcount
