"""
mcma.app.api.deps -- shared FastAPI dependencies: the authenticated
Principal (derived ONLY from the server-side session cookie) and CSRF
enforcement for state-changing requests.
"""

from __future__ import annotations

from ipaddress import ip_address

from fastapi import Request

from mcma.app.api.authz import Principal
from mcma.app.api.errors import ApiError
from mcma.app.auth.csrf import CSRF_COOKIE_NAME, CSRF_HEADER_NAME, verify_csrf_token
from mcma.app.auth.sessions import SESSION_COOKIE_NAME, SessionStore


def _is_loopback_client(request: Request) -> bool:
    client = request.client
    if client is None:
        return False
    try:
        return ip_address(client[0]).is_loopback
    except ValueError:
        return False


def get_principal_dependency(conn, session_store: SessionStore, local_user_id: str | None = None):
    """`local_user_id`, when set, is the single-office local install: this
    tool runs on ONE machine bound to loopback for ONE team, and making
    that employee invent an app password on top of the four portal
    passwords they already have adds a login without adding a boundary.

    It is NOT a bypass switch. The request must still come from loopback
    (checked per request, not once at startup), the user row must still
    exist and be active, and the Principal returned carries the same role
    and goes through the same permission and account-access checks as any
    other -- an account this user has not been granted is still invisible
    to it. A session cookie, when present, still wins, so a real login
    remains authoritative."""
    def _get_principal(request: Request) -> Principal:
        token = request.cookies.get(SESSION_COOKIE_NAME)
        user_id = session_store.validate(token) if token else None
        if user_id is None and local_user_id is not None and _is_loopback_client(request):
            user_id = local_user_id
        if user_id is None:
            raise ApiError(401, "UNAUTHENTICATED", "authentication required")
        row = conn.execute("SELECT user_id, username, role, active FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if row is None or not row["active"]:
            raise ApiError(401, "UNAUTHENTICATED", "authentication required")
        return Principal(row["user_id"], row["username"], row["role"])

    return _get_principal


def require_csrf(request: Request) -> None:
    cookie_token = request.cookies.get(CSRF_COOKIE_NAME)
    header_token = request.headers.get(CSRF_HEADER_NAME)
    if not verify_csrf_token(cookie_token, header_token):
        raise ApiError(403, "CSRF_FAILED", "CSRF validation failed")
