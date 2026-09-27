"""
mcma.app.auth.provider -- the AuthProvider seam (INC-16, review AR-L2).
A second provider (e.g. a future SSO/LDAP backend) can be substituted
without any other module ever referencing the concrete implementation --
domain/execution/notifications/portal never import this module at all
(only mcma.app's own request-handling code does).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol

from mcma.app.auth.passwords import verify_password


@dataclass(frozen=True)
class AuthenticatedUser:
    user_id: str
    username: str
    role: str


class AuthProvider(Protocol):
    def authenticate(self, username: str, password: str) -> Optional[AuthenticatedUser]: ...


class LocalUserAuthProvider:
    """The only concrete provider INC-16 ships: local users +
    Argon2id (mcma.app.auth.passwords), via the users table (INC-10)."""

    def __init__(self, conn) -> None:
        self._conn = conn

    # Verified for a username that does not exist, so a wrong username and a
    # wrong password cost the same and cannot be told apart by timing.
    _DUMMY_HASH: Optional[str] = None

    def _find(self, username: str):
        columns = "user_id, username, password_hash, role, active"
        row = self._conn.execute(f"SELECT {columns} FROM users WHERE username = ?", (username,)).fetchone()
        if row is not None:
            return row
        # Case-insensitive fallback, only when it is unambiguous.
        rows = self._conn.execute(
            f"SELECT {columns} FROM users WHERE lower(username) = lower(?)", (username.strip(),)
        ).fetchall()
        return rows[0] if len(rows) == 1 else None

    def authenticate(self, username: str, password: str) -> Optional[AuthenticatedUser]:
        if not isinstance(username, str) or not isinstance(password, str):
            return None
        row = self._find(username)
        if row is None:
            if LocalUserAuthProvider._DUMMY_HASH is None:
                from mcma.app.auth.passwords import hash_password

                LocalUserAuthProvider._DUMMY_HASH = hash_password("not-a-real-user-password")
            verify_password(LocalUserAuthProvider._DUMMY_HASH, password)
            return None
        if not row["active"]:
            return None
        if not verify_password(row["password_hash"], password):
            return None
        return AuthenticatedUser(row["user_id"], row["username"], row["role"])
