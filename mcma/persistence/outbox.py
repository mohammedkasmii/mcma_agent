"""
mcma.persistence.outbox -- SSE-facing retention/cursor semantics
(INC-15, DATA_MODEL.md §7/§8), built on top of the bare CRUD primitives
in mcma.persistence.repositories.outbox.

Retention is bounded by TIME AND COUNT, never by the minimum live
client's cursor -- a disconnected or idle client must never block
cleanup (DATA_MODEL.md §8).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional, Sequence

from mcma.persistence.repositories.outbox import EventOutboxRepository

DEFAULT_RETENTION_SECONDS = 7 * 24 * 3600
DEFAULT_RETENTION_COUNT = 10000


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def cleanup_retention(
    conn,
    *,
    retention_seconds: int = DEFAULT_RETENTION_SECONDS,
    keep_count: int = DEFAULT_RETENTION_COUNT,
) -> int:
    cutoff = (_utcnow() - timedelta(seconds=retention_seconds)).isoformat()
    return EventOutboxRepository(conn).delete_older_than(cutoff, keep_count)


def earliest_retained_event_id(conn) -> Optional[int]:
    return EventOutboxRepository(conn).earliest_event_id()


def latest_event_id(conn) -> int:
    return EventOutboxRepository(conn).latest_event_id()


def cursor_is_stale(conn, cursor: int) -> bool:
    """True when `cursor` predates retention -- a delta replay from it
    could silently skip events that were already cleaned up. The caller
    must force a full snapshot resync instead (DATA_MODEL.md §8)."""
    earliest = earliest_retained_event_id(conn)
    if earliest is None:
        return False  # nothing retained at all -- no gap possible
    return cursor < earliest - 1


def events_after(conn, cursor: int, account_ids: Optional[Sequence[str]] = None):
    account_ids_tuple = tuple(account_ids) if account_ids is not None else None
    return EventOutboxRepository(conn).events_after(cursor, account_ids_tuple)
