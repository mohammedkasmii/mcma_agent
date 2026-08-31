"""
mcma.app.api.deps -- shared FastAPI dependencies: the authenticated
Principal (derived ONLY from the server-side session cookie) and CSRF
enforcement for state-changing requests.
"""

from __future__ import annotations

from fastapi import Request

from mcma.app.api.authz import Principal
from mcma.app.api.errors import ApiError
from mcma.app.auth.csrf import CSRF_COOKIE_NAME, CSRF_HEADER_NAME, verify_csrf_token
from mcma.app.auth.sessions import SESSION_COOKIE_NAME, SessionStore


def get_principal_dependency(conn, session_store: SessionStore):
    def _get_principal(request: Request) -> Principal:
        token = request.cookies.get(SESSION_COOKIE_NAME)
        user_id = session_store.validate(token) if token else None
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
