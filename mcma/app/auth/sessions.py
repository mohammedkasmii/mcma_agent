"""
mcma.app.auth.sessions -- secure server-side sessions (INC-16,
API_CONTRACTS.md §2). The session TOKEN is the only thing that ever
leaves the server (as an HttpOnly/SameSite=strict/Secure cookie) -- the
session's own user_id/timestamps live server-side only, in this store.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

SESSION_COOKIE_NAME = "mcma_session"
IDLE_TIMEOUT_SECONDS = 30 * 60
ABSOLUTE_TIMEOUT_SECONDS = 12 * 3600


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class _ServerSession:
    user_id: str
    created_at: datetime
    last_seen_at: datetime


class SessionStore:
    """In-memory server-side session store. A real multi-worker
    deployment would back this with the DB or a shared cache; this
    project runs one Uvicorn worker (INC-11's OS mutex), so in-process
    state is sufficient and is never persisted or exposed to the client
    beyond the opaque token."""

    def __init__(
        self,
        *,
        idle_timeout_seconds: int = IDLE_TIMEOUT_SECONDS,
        absolute_timeout_seconds: int = ABSOLUTE_TIMEOUT_SECONDS,
    ) -> None:
        self._sessions: dict[str, _ServerSession] = {}
        self._idle_timeout_seconds = idle_timeout_seconds
        self._absolute_timeout_seconds = absolute_timeout_seconds

    def create(self, user_id: str) -> str:
        token = secrets.token_urlsafe(32)
        now = _utcnow()
        self._sessions[token] = _ServerSession(user_id, now, now)
        return token

    def validate(self, token: str) -> Optional[str]:
        """Returns the user_id if the session is valid (touching
        last_seen_at), else None -- idle expiry, absolute expiry, and an
        unknown token are all indistinguishable to the caller (fail
        closed, no information leak about WHY)."""
        session = self._sessions.get(token)
        if session is None:
            return None
        now = _utcnow()
        if (now - session.last_seen_at).total_seconds() > self._idle_timeout_seconds:
            del self._sessions[token]
            return None
        if (now - session.created_at).total_seconds() > self._absolute_timeout_seconds:
            del self._sessions[token]
            return None
        session.last_seen_at = now
        return session.user_id

    def invalidate(self, token: str) -> None:
        self._sessions.pop(token, None)


def set_session_cookie(response, token: str, *, secure: bool) -> None:
    """`secure` must be True in every non-loopback-dev deployment stage
    (review AR-L1) -- the caller supplies it from the serving
    configuration (TLS-only in production, INC-18), never hardcoded here."""
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        httponly=True,
        samesite="strict",
        secure=secure,
    )


def clear_session_cookie(response) -> None:
    response.delete_cookie(SESSION_COOKIE_NAME)
