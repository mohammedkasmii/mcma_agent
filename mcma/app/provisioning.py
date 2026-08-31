"""
mcma.app.provisioning -- safe, idempotent account/profile provisioning
and user-access assignment (pilot-integration correction, section 2).

Ensures the four canonical shared PortalAccount profiles exist (never
duplicated -- accounts.UNIQUE(entity, scope) is the durable backstop;
this module is idempotent on top of it) and provides small, explicit
helpers for granting an authenticated app user access to one of them.
This module never creates portal credentials/sessions itself (that is
tools/onboarding_tool.py's job, lease-guarded, after a human completes
the real login) -- it only manages the `accounts` and
`user_account_access` rows.
"""

from __future__ import annotations

from datetime import datetime, timezone

from mcma.domain.portal_accounts import THE_FOUR_PROFILES, PortalAccountProfile, canonical_account_id
from mcma.persistence.repositories.accounts import Account, AccountsRepository, UserAccountAccessRepository


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_canonical_accounts(conn) -> dict:
    """Idempotently ensures all four canonical profiles exist as
    `accounts` rows -- never creates a duplicate for the SAME (entity,
    scope) (accounts.UNIQUE(entity, scope) would reject that at the
    schema level regardless; this function just makes re-running it a
    safe no-op instead of an error). Returns {account_id: "created" |
    "already_existed"}."""
    repo = AccountsRepository(conn)
    result: dict = {}
    for profile in THE_FOUR_PROFILES:
        account_id = canonical_account_id(profile)
        existing = repo.get(account_id)
        if existing is not None:
            result[account_id] = "already_existed"
            continue
        repo.create(
            Account(
                account_id=account_id,
                label=f"{profile.entity.value} {profile.scope.value}",
                entity=profile.entity.value,
                scope=profile.scope.value,
                active=True,
                created_at=_utcnow_iso(),
            )
        )
        result[account_id] = "created"
    return result


def grant_user_access(conn, user_id: str, profile: PortalAccountProfile) -> None:
    """Grants an already-authenticated app user access to one canonical
    profile -- adding a new employee NEVER creates a new portal account
    row (section C), it only adds a user_account_access row against an
    EXISTING one. Fails closed if the profile's account row is missing
    (call ensure_canonical_accounts() first)."""
    account_id = canonical_account_id(profile)
    account = AccountsRepository(conn).get(account_id)
    if account is None:
        raise ValueError(
            f"no account row for {profile.entity.value}/{profile.scope.value} "
            f"(account_id={account_id!r}) -- call ensure_canonical_accounts() first"
        )
    UserAccountAccessRepository(conn).grant(user_id, account_id, _utcnow_iso())
