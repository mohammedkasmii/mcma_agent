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

    def authenticate(self, username: str, password: str) -> Optional[AuthenticatedUser]:
        row = self._conn.execute(
            "SELECT user_id, username, password_hash, role, active FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        if row is None or not row["active"]:
            return None
        if not verify_password(row["password_hash"], password):
            return None
        return AuthenticatedUser(row["user_id"], row["username"], row["role"])
