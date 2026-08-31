"""
mcma.app.api.authz -- permission + per-account authorization (INC-17,
correction #9). Every account-scoped check goes through here; no router
queries user_account_access directly.
"""

from __future__ import annotations

from dataclasses import dataclass

from mcma.app.api.errors import ApiError
from mcma.app.auth.permissions import Permission, role_has_permission
from mcma.persistence.repositories.accounts import UserAccountAccessRepository


@dataclass(frozen=True)
class Principal:
    """The authenticated actor for this request -- ALWAYS derived from
    the server-side session (mcma.app.auth.sessions), never from any
    client-supplied field. Every audit/job/execution record's actor
    comes from here."""

    user_id: str
    username: str
    role: str


def require_permission(principal: Principal, permission: Permission) -> None:
    if not role_has_permission(principal.role, permission):
        raise ApiError(403, "FORBIDDEN", "insufficient permission")


def require_account_access(conn, principal: Principal, account_id: str) -> None:
    """A global permission (e.g. jobs:plan) grants NOTHING until scoped
    to an account the user may see/act on."""
    if not UserAccountAccessRepository(conn).has_access(principal.user_id, account_id):
        raise ApiError(403, "FORBIDDEN", "no access to this account")


def visible_account_ids(conn, principal: Principal) -> frozenset:
    return frozenset(UserAccountAccessRepository(conn).accessible_accounts(principal.user_id))


def filter_rows_by_account_access(conn, principal: Principal, rows, account_id_key: str = "account_id") -> list:
    """Row-level filtering for list endpoints (review AR-H1): a global
    permission (e.g. jobs:view) must never return another account's rows
    just because the direct-account_id path wasn't used."""
    visible = visible_account_ids(conn, principal)
    return [row for row in rows if row[account_id_key] in visible]
