"""
mcma.persistence.repositories.accounts -- typed CRUD for accounts,
portal_sessions, users, role_permissions, user_account_access
(DATA_MODEL.md §2). Deliberately thin: constraint enforcement lives in the
schema (CHECK/UNIQUE/FK); this layer never re-implements a business rule
the database already guarantees.

portal_sessions row-level encryption (DPAPI) and rotation/revocation logic
belong to mcma.portal.vault (INC-13) -- this repository only performs the
plain SQL CRUD `storage_ref`/`status` operations vault.py builds on.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Account:
    account_id: str
    label: str
    entity: str
    scope: str
    active: bool
    created_at: str


class AccountsRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def create(self, account: Account) -> None:
        self._conn.execute(
            "INSERT INTO accounts (account_id, label, entity, scope, active, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (account.account_id, account.label, account.entity, account.scope, int(account.active), account.created_at),
        )

    def get(self, account_id: str) -> Optional[Account]:
        row = self._conn.execute(
            "SELECT account_id, label, entity, scope, active, created_at FROM accounts WHERE account_id = ?",
            (account_id,),
        ).fetchone()
        if row is None:
            return None
        return Account(row["account_id"], row["label"], row["entity"], row["scope"], bool(row["active"]), row["created_at"])

    def list_active(self) -> tuple[Account, ...]:
        rows = self._conn.execute(
            "SELECT account_id, label, entity, scope, active, created_at FROM accounts WHERE active = 1"
        ).fetchall()
        return tuple(
            Account(r["account_id"], r["label"], r["entity"], r["scope"], bool(r["active"]), r["created_at"])
            for r in rows
        )


class PortalSessionsRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def create(
        self, session_id: str, account_id: str, storage_ref: str, status: str, last_validated_at: Optional[str] = None
    ) -> None:
        self._conn.execute(
            "INSERT INTO portal_sessions (session_id, account_id, storage_ref, status, last_validated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (session_id, account_id, storage_ref, status, last_validated_at),
        )

    def get_for_account(self, account_id: str) -> Optional[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM portal_sessions WHERE account_id = ? ORDER BY rowid DESC LIMIT 1", (account_id,)
        ).fetchone()

    def set_status(self, session_id: str, status: str) -> None:
        self._conn.execute("UPDATE portal_sessions SET status = ? WHERE session_id = ?", (status, session_id))


class UsersRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def create(self, user_id: str, username: str, password_hash: str, role: str, active: bool = True) -> None:
        self._conn.execute(
            "INSERT INTO users (user_id, username, password_hash, role, active) VALUES (?, ?, ?, ?, ?)",
            (user_id, username, password_hash, role, int(active)),
        )

    def get_by_username(self, username: str) -> Optional[sqlite3.Row]:
        return self._conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()

    def get(self, user_id: str) -> Optional[sqlite3.Row]:
        return self._conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]


class RolePermissionsRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def grant(self, role: str, permission: str) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO role_permissions (role, permission) VALUES (?, ?)", (role, permission)
        )

    def permissions_for_role(self, role: str) -> tuple[str, ...]:
        rows = self._conn.execute("SELECT permission FROM role_permissions WHERE role = ?", (role,)).fetchall()
        return tuple(r["permission"] for r in rows)


class UserAccountAccessRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def grant(self, user_id: str, account_id: str, granted_at: str) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO user_account_access (user_id, account_id, granted_at) VALUES (?, ?, ?)",
            (user_id, account_id, granted_at),
        )

    def revoke(self, user_id: str, account_id: str) -> None:
        self._conn.execute(
            "DELETE FROM user_account_access WHERE user_id = ? AND account_id = ?", (user_id, account_id)
        )

    def accessible_accounts(self, user_id: str) -> tuple[str, ...]:
        rows = self._conn.execute(
            "SELECT account_id FROM user_account_access WHERE user_id = ?", (user_id,)
        ).fetchall()
        return tuple(r["account_id"] for r in rows)

    def has_access(self, user_id: str, account_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM user_account_access WHERE user_id = ? AND account_id = ?", (user_id, account_id)
        ).fetchone()
        return row is not None
