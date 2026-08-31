"""
mcma.persistence.repositories.jobs -- typed CRUD for automation_jobs and
job_inputs (DATA_MODEL.md §4/§4a). Deliberately bare: atomic enqueue, the
state machine, EXECUTE authorization, and restart reconciliation are
mcma.execution's job (INC-12) -- this layer only performs the SQL, inside
whatever transaction the caller has already opened (it never opens or
commits a transaction itself, so callers can compose it into an atomic
multi-table write).
"""

from __future__ import annotations

import sqlite3
from typing import Optional


class AutomationJobsRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def insert(
        self,
        job_id: str,
        account_id: str,
        requested_by_user_id: str,
        workflow_name: str,
        mode: str,
        status: str,
        input_hash: str,
        idempotency_key: str,
        created_at: str,
        state_version: int,
        parent_job_id: Optional[str] = None,
        plan_hash: Optional[str] = None,
        plan_snapshot: Optional[str] = None,
        authorized_by_user_id: Optional[str] = None,
    ) -> None:
        """`authorized_by_user_id` is normally NULL at insert (DRY_RUN has
        no authorizer yet) -- an EXECUTE job MAY set it here, atomically
        with its own creation, when the authorizer is already known at
        creation time (the caller of POST /executions), rather than a
        separate post-hoc update outside any transaction (Fable-review-2
        correction: that pattern skipped the version-bump/outbox-event
        invariant every other status change goes through)."""
        self._conn.execute(
            "INSERT INTO automation_jobs (job_id, account_id, requested_by_user_id, authorized_by_user_id, "
            "parent_job_id, workflow_name, mode, status, input_hash, plan_hash, plan_snapshot, "
            "idempotency_key, reason_code, created_at, started_at, finished_at, state_version) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, NULL, NULL, ?)",
            (
                job_id,
                account_id,
                requested_by_user_id,
                authorized_by_user_id,
                parent_job_id,
                workflow_name,
                mode,
                status,
                input_hash,
                plan_hash,
                plan_snapshot,
                idempotency_key,
                created_at,
                state_version,
            ),
        )

    def get(self, job_id: str) -> Optional[sqlite3.Row]:
        return self._conn.execute("SELECT * FROM automation_jobs WHERE job_id = ?", (job_id,)).fetchone()

    def get_by_idempotency_key(self, account_id: str, idempotency_key: str) -> Optional[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM automation_jobs WHERE account_id = ? AND idempotency_key = ?",
            (account_id, idempotency_key),
        ).fetchone()

    def update_status(
        self,
        job_id: str,
        status: str,
        state_version: int,
        *,
        reason_code: Optional[str] = None,
        plan_hash: Optional[str] = None,
        plan_snapshot: Optional[str] = None,
        authorized_by_user_id: Optional[str] = None,
        started_at: Optional[str] = None,
        finished_at: Optional[str] = None,
    ) -> None:
        row = self.get(job_id)
        if row is None:
            raise ValueError("no such job_id")
        self._conn.execute(
            "UPDATE automation_jobs SET status=?, state_version=?, "
            "reason_code=COALESCE(?, reason_code), plan_hash=COALESCE(?, plan_hash), "
            "plan_snapshot=COALESCE(?, plan_snapshot), authorized_by_user_id=COALESCE(?, authorized_by_user_id), "
            "started_at=COALESCE(?, started_at), finished_at=COALESCE(?, finished_at) "
            "WHERE job_id = ?",
            (
                status,
                state_version,
                reason_code,
                plan_hash,
                plan_snapshot,
                authorized_by_user_id,
                started_at,
                finished_at,
                job_id,
            ),
        )

    def list_non_terminal(self) -> tuple[sqlite3.Row, ...]:
        """Used by restart reconciliation (INC-12) -- every status not in
        the terminal set. Correction batch (human browser handoff):
        READY_FOR_HUMAN_REVIEW is REMOVED from this set (a restart during
        it must be reconciled to INTERRUPTED_NEEDS_HUMAN_REVIEW -- the
        browser context is no longer provably available); AWAITING_HUMAN_
        CONFIRMATION and HUMAN_CONFIRMED_COMPLETE are ADDED (must survive
        a restart untouched, awaiting only an explicit employee action).
        Kept in sync with mcma.execution.jobs.TERMINAL_STATUSES."""
        terminal = (
            "DRY_RUN_VERIFIED",
            "NEEDS_REVIEW",
            "IDENTITY_FAILED",
            "WRITE_ABORTED",
            "AWAITING_HUMAN_CONFIRMATION",
            "HUMAN_CONFIRMED_COMPLETE",
            "INTERRUPTED_NEEDS_HUMAN_REVIEW",
            "ABORTED_ON_RESTART",
            "ERROR",
        )
        placeholders = ",".join("?" for _ in terminal)
        rows = self._conn.execute(
            f"SELECT * FROM automation_jobs WHERE status NOT IN ({placeholders})", terminal
        ).fetchall()
        return tuple(rows)


class JobInputsRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def insert(
        self,
        job_id: str,
        content_hash: str,
        ciphertext: bytes,
        pii_class: str,
        created_at: str,
        expires_at: str,
    ) -> None:
        self._conn.execute(
            "INSERT INTO job_inputs (job_id, content_hash, ciphertext, pii_class, created_at, expires_at, deleted_at) "
            "VALUES (?, ?, ?, ?, ?, ?, NULL)",
            (job_id, content_hash, ciphertext, pii_class, created_at, expires_at),
        )

    def get(self, job_id: str) -> Optional[sqlite3.Row]:
        return self._conn.execute("SELECT * FROM job_inputs WHERE job_id = ?", (job_id,)).fetchone()

    def soft_delete(self, job_id: str, deleted_at: str) -> None:
        self._conn.execute("UPDATE job_inputs SET deleted_at = ? WHERE job_id = ?", (deleted_at, job_id))
