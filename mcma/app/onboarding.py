"""
mcma.app.onboarding -- the one-time local handoff endpoint (INC-13,
SAFETY_MODEL.md §7). Loopback-only, single-use, expiring tokens; NO
server-side browser is ever launched here -- the desktop onboarding tool
(tools/onboarding_tool.py) performs the actual headed login and hands the
resulting in-memory SessionMaterial to this endpoint over loopback HTTP.

This predates the real auth system (INC-16/17): it is a narrow,
purpose-built handoff, not a general API, and is bound to loopback only
for exactly that reason.
"""

from __future__ import annotations

import base64
import secrets
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from fastapi import FastAPI, HTTPException, Request

from mcma.portal.vault import AclVerifier, CryptoBackend, store_session

_TOKEN_TTL_SECONDS = 300
_LOOPBACK_HOSTS = ("127.0.0.1", "::1")


def _require_loopback(request: Request) -> None:
    client = request.client
    if client is None or client.host not in _LOOPBACK_HOSTS:
        raise HTTPException(status_code=403, detail="onboarding is loopback-only")


class OnboardingTokenStore:
    """In-memory, single-use, expiring tokens -- .pop() on consume makes
    a token unusable a second time even if network retries deliver the
    same request twice."""

    def __init__(self, ttl_seconds: int = _TOKEN_TTL_SECONDS) -> None:
        self._ttl_seconds = ttl_seconds
        self._tokens: dict[str, tuple[str, datetime]] = {}

    def issue(self, account_id: str) -> str:
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=self._ttl_seconds)
        self._tokens[token] = (account_id, expires_at)
        return token

    def consume(self, token: str) -> str:
        entry = self._tokens.pop(token, None)
        if entry is None:
            raise ValueError("invalid or already-used token")
        account_id, expires_at = entry
        if datetime.now(timezone.utc) > expires_at:
            raise ValueError("token expired")
        return account_id


def create_onboarding_app(
    *,
    conn,
    vault_dir,
    backend: CryptoBackend,
    acl_verifier: AclVerifier,
    lease_provider: Callable[[str], object],
    token_store: Optional[OnboardingTokenStore] = None,
) -> FastAPI:
    """`lease_provider(account_id)` must return an ALREADY-acquired
    LeaseHandle for that account -- this endpoint never acquires a lease
    itself, it only asserts the one it is given is valid immediately
    before replacing the session (test_service_acquires_lease_before_
    session_replace)."""
    app = FastAPI(title="MCMA Onboarding (loopback-only)")
    store = token_store or OnboardingTokenStore()

    @app.post("/onboarding/tokens/{account_id}")
    def issue_token(account_id: str, request: Request):
        _require_loopback(request)
        # Fable-review correction: previously issued a token for ANY
        # account_id string with no existence check -- any local process
        # could mint a token for an account it invented, then replace
        # that account's vault session via /onboarding/sessions. The
        # account must already be a real row before a token is minted
        # for it.
        row = conn.execute("SELECT 1 FROM accounts WHERE account_id = ?", (account_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="unknown account")
        return {"token": store.issue(account_id)}

    @app.post("/onboarding/sessions")
    async def submit_session(request: Request):
        _require_loopback(request)
        body = await request.json()
        token = body.get("token")
        storage_state_b64 = body.get("storage_state")
        if not token or not storage_state_b64:
            raise HTTPException(status_code=400, detail="token and storage_state are required")
        try:
            account_id = store.consume(token)
        except ValueError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc

        storage_state = base64.b64decode(storage_state_b64)
        lease_handle = lease_provider(account_id)
        await lease_handle.assert_valid()  # acquired BEFORE replace, re-checked here
        session_id = store_session(
            conn, lease_handle, account_id, storage_state,
            vault_dir=vault_dir, backend=backend, acl_verifier=acl_verifier,
        )
        return {"session_id": session_id}

    return app
