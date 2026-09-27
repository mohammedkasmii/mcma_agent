"""
mcma.app.auth.sessions -- secure server-side sessions (INC-16,
API_CONTRACTS.md §2). The session TOKEN is the only thing that ever
leaves the server (as an HttpOnly/SameSite=strict/Secure cookie) -- the
session's own user_id/timestamps live server-side only, in this store.
"""

from __future__ import annotations

import secrets
import threading
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
    beyond the opaque token.

    THREAD SAFETY. Sync FastAPI endpoints run on worker threads while async
    endpoints and the SSE stream run on the event loop, and several employee
    browsers hit all of them at once. Every method takes one lock, so a
    validate() (which mutates last_seen_at and may delete an expired
    session) can never interleave with create()/invalidate() or corrupt the
    dict. State is in memory ONLY: restarting the server invalidates every
    session and employees must sign in again."""

    def __init__(
        self,
        *,
        idle_timeout_seconds: int = IDLE_TIMEOUT_SECONDS,
        absolute_timeout_seconds: int = ABSOLUTE_TIMEOUT_SECONDS,
    ) -> None:
        self._sessions: dict[str, _ServerSession] = {}
        self._lock = threading.RLock()
        self._idle_timeout_seconds = idle_timeout_seconds
        self._absolute_timeout_seconds = absolute_timeout_seconds

    def create(self, user_id: str) -> str:
        token = secrets.token_urlsafe(32)
        now = _utcnow()
        with self._lock:
            self._sessions[token] = _ServerSession(user_id, now, now)
        return token

    def validate(self, token: str) -> Optional[str]:
        """Returns the user_id if the session is valid (touching
        last_seen_at), else None -- idle expiry, absolute expiry, and an
        unknown token are all indistinguishable to the caller (fail
        closed, no information leak about WHY)."""
        with self._lock:
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

    def peek(self, token: str) -> Optional[str]:
        """Like validate(), but NEVER touches last_seen_at. Used by the SSE
        stream to ask "is this session still alive?" every second: an open
        event stream must not keep an otherwise idle session alive forever,
        so the idle timer only advances on real requests. Expired sessions
        are still reported as gone (and removed)."""
        with self._lock:
            session = self._sessions.get(token)
            if session is None:
                return None
            now = _utcnow()
            if (now - session.last_seen_at).total_seconds() > self._idle_timeout_seconds or (
                now - session.created_at
            ).total_seconds() > self._absolute_timeout_seconds:
                del self._sessions[token]
                return None
            return session.user_id

    def invalidate(self, token: str) -> None:
        with self._lock:
            self._sessions.pop(token, None)

    def invalidate_user(self, user_id: str) -> int:
        """Drops every live session of one user (deactivation, demotion,
        password reset). Returns how many were dropped."""
        with self._lock:
            doomed = [t for t, s in self._sessions.items() if s.user_id == user_id]
            for token in doomed:
                del self._sessions[token]
            return len(doomed)


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


def clear_session_cookie(response, *, secure: bool = True) -> None:
    """Expires the session cookie with EXACTLY the attributes it was set
    with (path, Secure, HttpOnly, SameSite=strict) so the browser treats it
    as the same cookie and removes it."""
    response.delete_cookie(SESSION_COOKIE_NAME, path="/", secure=secure, httponly=True, samesite="strict")


def clear_csrf_cookie(response, *, secure: bool = True) -> None:
    """The CSRF cookie is readable by JavaScript (httponly=False), Secure and
    SameSite=strict -- cleared with the same attributes."""
    from mcma.app.auth.csrf import CSRF_COOKIE_NAME

    response.delete_cookie(CSRF_COOKIE_NAME, path="/", secure=secure, httponly=False, samesite="strict")
