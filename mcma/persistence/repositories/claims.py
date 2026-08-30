"""
mcma.persistence.repositories.claims -- typed CRUD for claims, categories,
category_presence, poll_runs, poll_run_categories, unmatched_notifications,
observed_finalizations (DATA_MODEL.md §3). The category-scoped three-poll
lifecycle rule itself is implemented in mcma.notifications (INC-14); this
layer only provides the storage primitives and the schema-level integrity
guarantees (composite FK, UNIQUE, CHECK) that make the rule enforceable.
"""

from __future__ import annotations

import sqlite3
from typing import Optional


class ClaimsRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def upsert(
        self,
        claim_pk: str,
        account_id: str,
        portal_claim_id: str,
        version: int,
        reference: Optional[str] = None,
        insured: Optional[str] = None,
        police: Optional[str] = None,
        matricule_norm: Optional[str] = None,
    ) -> str:
        """portal_claim_id (idSinistre) is REQUIRED -- a caller with none
        must route to unmatched_notifications instead, never insert here
        with a blank/None value (the NOT NULL constraint also enforces
        this at the schema level)."""
        if not portal_claim_id:
            raise ValueError("claims.portal_claim_id is required; use unmatched_notifications otherwise")
        existing = self._conn.execute(
            "SELECT claim_pk FROM claims WHERE account_id = ? AND portal_claim_id = ?",
            (account_id, portal_claim_id),
        ).fetchone()
        if existing is not None:
            self._conn.execute(
                "UPDATE claims SET reference=?, insured=?, police=?, matricule_norm=?, last_seen_version=? "
                "WHERE claim_pk = ?",
                (reference, insured, police, matricule_norm, version, existing["claim_pk"]),
            )
            return existing["claim_pk"]
        self._conn.execute(
            "INSERT INTO claims (claim_pk, account_id, portal_claim_id, reference, insured, police, "
            "matricule_norm, first_seen_version, last_seen_version) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (claim_pk, account_id, portal_claim_id, reference, insured, police, matricule_norm, version, version),
        )
        return claim_pk

    def get(self, claim_pk: str) -> Optional[sqlite3.Row]:
        return self._conn.execute("SELECT * FROM claims WHERE claim_pk = ?", (claim_pk,)).fetchone()

    def get_by_portal_claim_id(self, account_id: str, portal_claim_id: str) -> Optional[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM claims WHERE account_id = ? AND portal_claim_id = ?", (account_id, portal_claim_id)
        ).fetchone()


class CategoriesRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def ensure(self, code_alerte: str, label: str) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO categories (code_alerte, label) VALUES (?, ?)", (code_alerte, label)
        )


class CategoryPresenceRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def ensure_row(self, account_id: str, claim_pk: str, category_code: str, since_version: int) -> None:
        """Creates the (account_id, claim_pk, category_code) row if absent,
        defaulting present=1/ACTIVE/count=0 -- idempotent, never overwrites
        an existing row's lifecycle state."""
        self._conn.execute(
            "INSERT OR IGNORE INTO category_presence "
            "(account_id, claim_pk, category_code, present, presence_status, consecutive_absence_count, since_version) "
            "VALUES (?, ?, ?, 1, 'ACTIVE', 0, ?)",
            (account_id, claim_pk, category_code, since_version),
        )

    def get(self, account_id: str, claim_pk: str, category_code: str) -> Optional[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM category_presence WHERE account_id = ? AND claim_pk = ? AND category_code = ?",
            (account_id, claim_pk, category_code),
        ).fetchone()

    def update_lifecycle(
        self,
        account_id: str,
        claim_pk: str,
        category_code: str,
        *,
        present: bool,
        presence_status: str,
        consecutive_absence_count: int,
        last_complete_poll_version: Optional[int],
        last_seen_poll_run_id: Optional[str],
    ) -> None:
        self._conn.execute(
            "UPDATE category_presence SET present=?, presence_status=?, consecutive_absence_count=?, "
            "last_complete_poll_version=?, last_seen_poll_run_id=? "
            "WHERE account_id=? AND claim_pk=? AND category_code=?",
            (
                int(present),
                presence_status,
                consecutive_absence_count,
                last_complete_poll_version,
                last_seen_poll_run_id,
                account_id,
                claim_pk,
                category_code,
            ),
        )

    def list_for_account(self, account_id: str) -> tuple[sqlite3.Row, ...]:
        return tuple(
            self._conn.execute(
                "SELECT * FROM category_presence WHERE account_id = ?", (account_id,)
            ).fetchall()
        )


class PollRunsRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def create(
        self, poll_run_id: str, account_id: str, started_at: str, status: str, session_valid: bool,
        completed_at: Optional[str] = None,
    ) -> None:
        self._conn.execute(
            "INSERT INTO poll_runs (poll_run_id, account_id, started_at, completed_at, status, session_valid) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (poll_run_id, account_id, started_at, completed_at, status, int(session_valid)),
        )

    def get(self, poll_run_id: str) -> Optional[sqlite3.Row]:
        return self._conn.execute("SELECT * FROM poll_runs WHERE poll_run_id = ?", (poll_run_id,)).fetchone()


class PollRunCategoriesRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def create(
        self,
        poll_run_id: str,
        category_code: str,
        status: str,
        session_valid: bool,
        completed_at: Optional[str] = None,
        rows_seen: Optional[int] = None,
    ) -> None:
        self._conn.execute(
            "INSERT INTO poll_run_categories (poll_run_id, category_code, status, session_valid, completed_at, rows_seen) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (poll_run_id, category_code, status, int(session_valid), completed_at, rows_seen),
        )

    def get(self, poll_run_id: str, category_code: str) -> Optional[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM poll_run_categories WHERE poll_run_id = ? AND category_code = ?",
            (poll_run_id, category_code),
        ).fetchone()


class UnmatchedNotificationsRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def create(
        self, staging_id: str, account_id: str, raw_payload: str, seen_at: str, reference: Optional[str] = None
    ) -> None:
        self._conn.execute(
            "INSERT INTO unmatched_notifications (staging_id, account_id, reference, raw_payload, seen_at, resolved) "
            "VALUES (?, ?, ?, ?, ?, 0)",
            (staging_id, account_id, reference, raw_payload, seen_at),
        )

    def list_for_account(self, account_id: str) -> tuple[sqlite3.Row, ...]:
        return tuple(
            self._conn.execute(
                "SELECT * FROM unmatched_notifications WHERE account_id = ?", (account_id,)
            ).fetchall()
        )


class ObservedFinalizationsRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def record(
        self, claim_pk: str, observed_at: str, evidence_source: str, poll_run_id: Optional[str] = None
    ) -> None:
        self._conn.execute(
            "INSERT INTO observed_finalizations (claim_pk, observed_at, evidence_source, poll_run_id) "
            "VALUES (?, ?, ?, ?)",
            (claim_pk, observed_at, evidence_source, poll_run_id),
        )

    def list_for_claim(self, claim_pk: str) -> tuple[sqlite3.Row, ...]:
        return tuple(
            self._conn.execute(
                "SELECT * FROM observed_finalizations WHERE claim_pk = ?", (claim_pk,)
            ).fetchall()
        )
