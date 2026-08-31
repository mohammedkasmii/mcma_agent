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

from mcma.notifications.extract import run_poll
from mcma.persistence.leases import LeaseNotHeld, acquire_lease
from mcma.persistence.repositories.accounts import AccountsRepository
from mcma.persistence.repositories.outbox import AccountStateVersionRepository
from mcma.portal.capabilities import open_reader
from mcma.portal.sinauto_contracts import notification_contracts, portal_base_for
from mcma.portal.vault import load_and_verify_session


async def poll_one_account(
    conn, browser, account_id: str, category_codes, *,
    instance_id: str, allowed_host: str, vault_dir, crypto_backend,
    entity: str = "MCMA",
) -> str:
    """Polls every category for ONE account. Returns a short outcome
    string for the caller to log; never raises for an expected failure
    (no session yet, lease held elsewhere, portal unreachable), because
    those are ordinary states in an office where four accounts share one
    portal and sessions expire on their own schedule."""
    try:
        lease = acquire_lease(conn, account_id, instance_id, ttl_seconds=120)
    except LeaseNotHeld:
        # Another job holds the account -- a form job in progress, most
        # likely. Its work matters more than a notification refresh.
        return "LEASE_BUSY"

    try:
        try:
            raw_session = load_and_verify_session(
                conn, account_id, vault_dir=vault_dir, backend=crypto_backend
            )
        except Exception:
            # No usable session: this account has not been logged in yet,
            # or its session expired. The dashboard shows that state per
            # account; it is not an error to report here.
            return "NO_SESSION"

        contracts = notification_contracts(allowed_host, category_codes, entity)
        try:
            reader = await open_reader(
                browser, lease, contracts, allowed_host,
                context_options={"storage_state": json.loads(raw_session)},
                portal_base=portal_base_for(entity),
            )
        except Exception:
            return "READER_UNAVAILABLE"

        try:
            version = AccountStateVersionRepository(conn).bump(account_id)
            await run_poll(conn, account_id, reader, tuple(category_codes), version)
            return "POLLED"
        finally:
            await reader.close()
    finally:
        lease.release()


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
