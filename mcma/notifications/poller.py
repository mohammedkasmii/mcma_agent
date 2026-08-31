"""
mcma.notifications.poller -- drives mcma.notifications.extract
for each account on a schedule.

run_poll() has existed since INC-14, fully tested, with ZERO callers
anywhere outside the test suite. Nothing in the assembled application
ever fetched a notification, so the claims table it populates stayed
permanently empty and the dashboard reading from it had nothing to show.
This is the missing caller.

One account at a time, by construction. Each account gets its own lease,
its own session, its own reader and its own poll run; nothing here
accepts a list of accounts for a single reader, and a failure polling one
account never touches another's data. Two accounts operated from the same
office (Oujda and Nador) are simply two independent passes.

Read-only throughout: the only capability constructed here is a
ReadCapability, which has no write method and no upgrade path to one.

Lives in mcma.notifications rather than mcma.execution because the two
are SIBLING layers -- neither may import the other -- and this is
notification work. It therefore takes the few settings it needs as plain
arguments instead of a RunnerConfig, which would have dragged the
execution layer in through the type alone.
"""

from __future__ import annotations

import json
import logging

from mcma.notifications.extract import run_poll

logger = logging.getLogger(__name__)
from mcma.persistence.leases import LeaseNotHeld, acquire_lease
from mcma.persistence.repositories.accounts import AccountsRepository
from mcma.persistence.repositories.outbox import AccountStateVersionRepository
from mcma.portal.capabilities import open_reader
from mcma.portal.sinauto_contracts import (
    category_discovery_contracts,
    notification_contracts,
    portal_base_for,
)
from mcma.portal.vault import load_and_verify_session, revoke_session


async def poll_one_account(
    conn, browser, account_id: str, category_codes, *,
    instance_id: str, allowed_host: str, vault_dir, crypto_backend,
    entity: str = "MCMA",
) -> str:
    """Polls every category for ONE account. Returns a short outcome
    string; never raises for an expected state, because in an office where
    four accounts share one portal and sessions expire on their own
    schedule, "not logged in" and "someone is filling a dossier" are
    ordinary, not errors.

    `category_codes` may be empty, which means discover them from the
    portal. There is no reviewed fixed list of alert codes anywhere in
    this repository -- the categories table ships empty -- and the
    baseline read them from the portal's own notification surface, so a
    configured list is an override rather than the normal path."""
    try:
        lease = acquire_lease(conn, account_id, instance_id, ttl_seconds=180)
    except LeaseNotHeld:
        # A dossier fill holds the account. Its work matters more than a
        # notification refresh, and a refresh must never make it wait.
        return "LEASE_BUSY"

    try:
        try:
            raw_session = load_and_verify_session(
                conn, account_id, vault_dir=vault_dir, backend=crypto_backend
            )
        except Exception:
            # Never logged in, or the stored session is gone. Reported,
            # not raised: the other three accounts still poll.
            return "NO_SESSION"

        storage_state = json.loads(raw_session)
        base = portal_base_for(entity)

        # Two contexts, deliberately. Discovery runs with NO getAlerte
        # contract installed, so it is structurally incapable of fetching
        # what it discovers; the fetch context is then built from the
        # validated codes. Contracts stay fixed at context creation, and a
        # code that arrived from the portal cannot widen the policy of the
        # context that found it.
        codes = tuple(category_codes)
        if not codes:
            try:
                discovery = await open_reader(
                    browser, lease, category_discovery_contracts(allowed_host, entity),
                    allowed_host, context_options={"storage_state": storage_state},
                    portal_base=base,
                )
            except Exception:
                return "PORTAL_UNAVAILABLE"
            try:
                codes = await discovery.discover_notification_categories()
            except Exception:
                # A portal that will not show its alert list to this
                # session is the signature of an expired one.
                return _mark_reconnect_required(conn, account_id, vault_dir)
            finally:
                await discovery.close()

        if not codes:
            # No categories offered. NOT the same as "every alert is
            # gone": nothing is read, so run_poll is never called and no
            # presence lifecycle advances on this evidence.
            return "NO_CATEGORIES"

        try:
            reader = await open_reader(
                browser, lease, notification_contracts(allowed_host, codes, entity),
                allowed_host, context_options={"storage_state": storage_state},
                portal_base=base,
            )
        except Exception:
            return "PORTAL_UNAVAILABLE"

        try:
            version = AccountStateVersionRepository(conn).bump(account_id)
            await run_poll(conn, account_id, reader, codes, version)
            return "POLLED"
        finally:
            await reader.close()
    finally:
        lease.release()


def _mark_reconnect_required(conn, account_id: str, vault_dir) -> str:
    """Reuses the existing session model rather than inventing a second
    definition of "connected": the ACTIVE row is revoked, so
    load_and_verify_session finds nothing and /accounts stops reporting
    the account as connected. Because a revoked row still EXISTS, the
    dashboard can tell "was connected, needs reconnecting" from "never
    connected" without any new state."""
    try:
        revoke_session(conn, account_id, vault_dir=vault_dir)
    except Exception:
        logger.warning("could not revoke the expired session for one account", exc_info=True)
    return "RECONNECT_REQUIRED"


async def poll_all_accounts(
    conn, browser, category_codes, *,
    instance_id: str, allowed_host: str, vault_dir, crypto_backend,
) -> dict:
    """One pass over every active account this installation knows about.

    MAMDA accounts are polled too: they cannot be written to, but their
    notifications are exactly the work an employee needs to track, and
    the read path used here cannot write regardless of which account it
    is pointed at."""
    outcomes = {}
    for account in AccountsRepository(conn).list_active():
        try:
            outcomes[account.account_id] = await poll_one_account(
                conn, browser, account.account_id, category_codes,
                instance_id=instance_id, allowed_host=allowed_host,
                vault_dir=vault_dir, crypto_backend=crypto_backend,
                entity=account.entity,
            )
        except Exception as exc:  # pragma: no cover - defensive isolation only
            # One account's unexpected failure must never stop the others.
            outcomes[account.account_id] = f"ERROR_{type(exc).__name__}"
    return outcomes
