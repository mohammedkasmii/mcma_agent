"""
mcma.app.portal_login -- capture a portal session for ONE account, from
the dashboard.

Until now the only way to log an account in was tools/onboarding_tool.py:
a separate command-line program an operator ran by hand, which opened its
own browser and posted the captured session to a loopback endpoint. That
is a reasonable shape for a technician and a poor one for the person who
actually works here, who needs four accounts logged in and has no reason
to meet a terminal.

The safety properties of that tool are kept exactly. The human still
performs the login and the OTP themselves in a visible browser:
LoginCapability navigates only to the single reviewed GET login route,
polls only fixed logged-in markers, and has no method that accepts a
credential or fills a form. Nothing here ever sees or stores a password.

What changes is only who drives it. The service already holds the
account's lease and the vault, so the captured session goes straight into
encrypted storage without a second process, a loopback HTTP hop, or a
single-use token to shuttle between them -- the token existed to protect
a handoff that no longer happens.

SessionMaterial is consumed exactly once, immediately, and never logged.
"""

from __future__ import annotations

import json
from pathlib import Path

from mcma.persistence.leases import acquire_lease
from mcma.portal.capabilities import open_login_session
from mcma.portal.sinauto_contracts import auth_contracts
from mcma.portal.vault import store_session


class PortalLoginFailed(Exception):
    """The human did not complete the login in time, or the browser could
    not be opened. Carries no portal text and no credential material --
    only a short fixed reason, so a caller can tell the failures apart
    without ever surfacing what the portal said."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


async def capture_session_for_account(
    conn,
    browser,
    account_id: str,
    *,
    instance_id: str,
    allowed_host: str,
    vault_dir: Path,
    crypto_backend,
    acl_verifier,
    timeout_seconds: float = 300.0,
) -> str:
    """Opens a visible browser at the portal's login page, waits for the
    human to finish signing in (including the SMS OTP), and stores the
    resulting session encrypted for this ONE account.

    The lease is held for the whole capture so a form job cannot start
    against the account while its session is being replaced. Returns the
    stored session_id."""
    lease = acquire_lease(conn, account_id, instance_id, ttl_seconds=int(timeout_seconds) + 120)
    try:
        try:
            login = await open_login_session(
                browser, account_id, auth_contracts(allowed_host), allowed_host
            )
        except Exception as exc:
            raise PortalLoginFailed("LOGIN_PAGE_UNREACHABLE") from exc

        try:
            material = await login.perform_manual_login(timeout_seconds=timeout_seconds)
        except Exception as exc:
            # Includes LoginTimedOut. The message deliberately carries no
            # portal response text.
            raise PortalLoginFailed("NOT_COMPLETED_" + type(exc).__name__) from exc
        finally:
            await login.close()

        storage_state = material.consume_for_handoff()
        return store_session(
            conn,
            lease,
            account_id,
            json.dumps(storage_state).encode("utf-8"),
            vault_dir=vault_dir,
            backend=crypto_backend,
            acl_verifier=acl_verifier,
        )
    finally:
        lease.release()
