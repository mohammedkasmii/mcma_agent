"""
mcma.app.auth.bootstrap -- secure first-admin bootstrap (INC-16,
API_CONTRACTS.md §2). Local-only (loopback), single-use, expiring;
disabled entirely once any user exists. A LAN caller can never claim it
-- the loopback check happens at the transport/endpoint layer
(mcma.app.auth.bootstrap_app below), not merely by convention.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException, Request

from mcma.app.auth.passwords import hash_password

BOOTSTRAP_TOKEN_TTL_SECONDS = 600
_LOOPBACK_HOSTS = ("127.0.0.1", "::1")


class BootstrapUnavailable(Exception):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class BootstrapTokenStore:
    """Single-use, expiring, in-memory. Issuing a NEW token before the
    previous one was consumed simply replaces it (the old one becomes
    unusable) -- there is never more than one live bootstrap token."""

    def __init__(self, ttl_seconds: int = BOOTSTRAP_TOKEN_TTL_SECONDS) -> None:
        self._ttl_seconds = ttl_seconds
        self._token: Optional[str] = None
        self._expires_at: Optional[datetime] = None

    def issue(self) -> str:
        self._token = secrets.token_urlsafe(32)
        self._expires_at = _utcnow() + timedelta(seconds=self._ttl_seconds)
        return self._token

    def consume(self, token: str) -> None:
        if self._token is None or not secrets.compare_digest(token, self._token):
            raise BootstrapUnavailable("invalid or already-used bootstrap token")
        if _utcnow() > self._expires_at:
            self._token = None
            raise BootstrapUnavailable("bootstrap token expired")
        self._token = None  # single-use, regardless of outcome


def _require_loopback(request: Request) -> None:
    client = request.client
    if client is None or client.host not in _LOOPBACK_HOSTS:
        raise HTTPException(status_code=403, detail="bootstrap is loopback-only")


def create_bootstrap_app(conn, *, token_store: Optional[BootstrapTokenStore] = None) -> FastAPI:
    app = FastAPI(title="MCMA First-Admin Bootstrap (loopback-only)")
    store = token_store or BootstrapTokenStore()

    def _admin_exists() -> bool:
        row = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()
        return row["c"] > 0

    @app.post("/bootstrap/tokens")
    def issue_token(request: Request):
        _require_loopback(request)
        if _admin_exists():
            raise HTTPException(status_code=403, detail="bootstrap is disabled: an admin already exists")
        return {"token": store.issue()}

    @app.post("/bootstrap/admin")
    async def create_first_admin(request: Request):
        _require_loopback(request)
        if _admin_exists():
            raise HTTPException(status_code=403, detail="bootstrap is disabled: an admin already exists")
        body = await request.json()
        token = body.get("token")
        username = body.get("username")
        password = body.get("password")
        if not token or not username or not password:
            raise HTTPException(status_code=400, detail="token, username, and password are required")
        try:
            store.consume(token)
        except BootstrapUnavailable as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc

        user_id = uuid.uuid4().hex
        conn.execute(
            "INSERT INTO users (user_id, username, password_hash, role, active) VALUES (?, ?, ?, 'admin', 1)",
            (user_id, username, hash_password(password)),
        )
        # The first admin is granted every provisioned account.
        #
        # Without this the account was created with access to NOTHING:
        # visible_account_ids() reads user_account_access, which was
        # empty, so /accounts returned [] and the dashboard rendered with
        # no accounts on it at all -- and since no endpoint grants access,
        # there was no way out of that state short of editing the
        # database by hand. A first admin who cannot see the office's own
        # four accounts is not a usable starting state.
        #
        # This grants access to accounts that ALREADY EXIST (provisioning
        # created them); it never creates a portal account, and it applies
        # only to the single first admin -- every later user starts with
        # no access and must be granted it explicitly.
        granted = conn.execute("SELECT account_id FROM accounts").fetchall()
        for row in granted:
            conn.execute(
                "INSERT OR IGNORE INTO user_account_access (user_id, account_id, granted_at) "
                "VALUES (?, ?, ?)",
                (user_id, row["account_id"], _utcnow().isoformat()),
            )
        return {"user_id": user_id, "username": username, "accounts": len(granted)}

    return app
