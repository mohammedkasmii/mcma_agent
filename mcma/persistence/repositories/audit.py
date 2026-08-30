"""
mcma.persistence.repositories.audit -- typed CRUD for employee_actions and
audit_events (DATA_MODEL.md §6). audit_events stores hashes/redactions
only -- callers must never pass a raw secret/PII payload as before_hash/
after_hash; this layer does not itself hash anything (that is the
caller's job, so the hashing algorithm stays visible/auditable at the
call site).
"""

from __future__ import annotations

import sqlite3
from typing import Optional


class EmployeeActionsRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def create(
        self, action_id: str, claim_pk: str, status: str, actor_user_id: str, updated_at: str, version: int,
        note: Optional[str] = None,
    ) -> None:
        self._conn.execute(
            "INSERT INTO employee_actions (action_id, claim_pk, status, note, actor_user_id, updated_at, version) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (action_id, claim_pk, status, note, actor_user_id, updated_at, version),
        )

    def list_for_claim(self, claim_pk: str) -> tuple[sqlite3.Row, ...]:
        return tuple(
            self._conn.execute(
                "SELECT * FROM employee_actions WHERE claim_pk = ? ORDER BY version", (claim_pk,)
            ).fetchall()
        )


class AuditEventsRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def record(
        self,
        audit_id: str,
        action: str,
        created_at: str,
        actor_user_id: Optional[str] = None,
        account_id: Optional[str] = None,
        job_id: Optional[str] = None,
        before_hash: Optional[str] = None,
        after_hash: Optional[str] = None,
    ) -> None:
        self._conn.execute(
            "INSERT INTO audit_events (audit_id, actor_user_id, account_id, job_id, action, before_hash, "
            "after_hash, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (audit_id, actor_user_id, account_id, job_id, action, before_hash, after_hash, created_at),
        )

    def list_for_account(self, account_id: str) -> tuple[sqlite3.Row, ...]:
        return tuple(
            self._conn.execute(
                "SELECT * FROM audit_events WHERE account_id = ? ORDER BY created_at", (account_id,)
            ).fetchall()
        )
