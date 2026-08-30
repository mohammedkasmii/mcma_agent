"""
mcma.persistence.repositories.outbox -- bare CRUD primitives for
account_state_version and event_outbox (DATA_MODEL.md §7). This is the
storage layer only, composable into a caller's own transaction (it never
opens/commits one itself) so job/notification state changes and their
outbox event land atomically. The SSE-facing retention/cursor/resync
semantics (DATA_MODEL.md §8) are built on top of this in mcma.app.sse
(INC-15) -- deliberately not duplicated here.
"""

from __future__ import annotations

import sqlite3
from typing import Optional


class AccountStateVersionRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def bump(self, account_id: str) -> int:
        """Atomically increments (or initializes to 1) the account's
        monotonic version and returns the new value. Composable into the
        caller's own open transaction."""
        row = self._conn.execute(
            "SELECT version FROM account_state_version WHERE account_id = ?", (account_id,)
        ).fetchone()
        if row is None:
            self._conn.execute(
                "INSERT INTO account_state_version (account_id, version) VALUES (?, 1)", (account_id,)
            )
            return 1
        new_version = row["version"] + 1
        self._conn.execute(
            "UPDATE account_state_version SET version = ? WHERE account_id = ?", (new_version, account_id)
        )
        return new_version

    def current(self, account_id: str) -> int:
        row = self._conn.execute(
            "SELECT version FROM account_state_version WHERE account_id = ?", (account_id,)
        ).fetchone()
        return row["version"] if row is not None else 0


class EventOutboxRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def insert(
        self,
        account_id: str,
        account_state_version: int,
        aggregate: str,
        event_type: str,
        payload_json: str,
        created_at: str,
    ) -> int:
        """payload_json must never contain PII (DATA_MODEL.md §9) -- this
        layer does not scrub it; callers are responsible for building a
        safe payload. Returns the new global event_id."""
        cursor = self._conn.execute(
            "INSERT INTO event_outbox (account_id, account_state_version, aggregate, type, payload_json, "
            "created_at, published_at) VALUES (?, ?, ?, ?, ?, ?, NULL)",
            (account_id, account_state_version, aggregate, event_type, payload_json, created_at),
        )
        event_id = cursor.lastrowid
        assert event_id is not None  # AUTOINCREMENT INSERT always yields a rowid
        return event_id

    def events_after(self, cursor: int, account_ids: Optional[tuple[str, ...]] = None) -> tuple[sqlite3.Row, ...]:
        if account_ids is None:
            rows = self._conn.execute(
                "SELECT * FROM event_outbox WHERE event_id > ? ORDER BY event_id", (cursor,)
            ).fetchall()
        else:
            placeholders = ",".join("?" for _ in account_ids)
            rows = self._conn.execute(
                f"SELECT * FROM event_outbox WHERE event_id > ? AND account_id IN ({placeholders}) ORDER BY event_id",
                (cursor, *account_ids),
            ).fetchall()
        return tuple(rows)

    def earliest_event_id(self) -> Optional[int]:
        row = self._conn.execute("SELECT MIN(event_id) AS m FROM event_outbox").fetchone()
        return row["m"] if row is not None else None

    def latest_event_id(self) -> int:
        row = self._conn.execute("SELECT MAX(event_id) AS m FROM event_outbox").fetchone()
        return row["m"] if row is not None and row["m"] is not None else 0

    def delete_older_than(self, cutoff_created_at: str, keep_count: int) -> int:
        """Time-and-count retention (DATA_MODEL.md §8): deletes events
        older than cutoff_created_at, but never below keep_count most
        recent rows overall -- independent of any connected client's
        cursor position."""
        total = self._conn.execute("SELECT COUNT(*) AS c FROM event_outbox").fetchone()["c"]
        if total <= keep_count:
            return 0
        deletable = total - keep_count
        cursor = self._conn.execute(
            "DELETE FROM event_outbox WHERE event_id IN ("
            "  SELECT event_id FROM event_outbox WHERE created_at < ? ORDER BY event_id LIMIT ?"
            ")",
            (cutoff_created_at, deletable),
        )
        return cursor.rowcount
