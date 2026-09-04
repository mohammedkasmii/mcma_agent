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
from mcma.persistence.leases import LeaseNotHeld, acquire_lease
from mcma.persistence.repositories.accounts import AccountsRepository
from mcma.persistence.repositories.claims import CategoriesRepository
from mcma.persistence.repositories.outbox import AccountStateVersionRepository
from mcma.portal.capabilities import is_valid_category_code, open_reader
from mcma.portal.sinauto_contracts import (
    category_discovery_contracts,
    notification_contracts,
    portal_base_for,
)
from mcma.portal.vault import load_and_verify_session, revoke_session

logger = logging.getLogger(__name__)


async def poll_one_account(
    conn, browser, account_id: str, category_codes, *,
    instance_id: str, allowed_host: str, vault_dir, crypto_backend,
    entity: str = "MCMA",
    session_observer=None,
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
        # CONFIGURED codes are validated exactly like discovered ones. A
        # value from a settings file is no more trustworthy as a URL
        # segment than one scraped from a page, and `../evil` must be
        # rejected here rather than relying on percent-encoding downstream.
        # Materialized once: category_codes may be any iterable, and
        # consuming it twice would leave the second pass empty and the
        # count wrong.
        configured_codes = tuple(category_codes)
        codes = tuple(code for code in configured_codes if is_valid_category_code(code))
        if len(codes) != len(configured_codes):
            logger.warning("ignoring one or more malformed configured category codes")
        if not codes:
            try:
                discovery = await open_reader(
                    browser, lease, category_discovery_contracts(allowed_host, entity),
                    allowed_host, context_options={"storage_state": storage_state},
                    portal_base=base,
                )
            except Exception as exc:
                _log_unavailable("discovery reader could not open", exc=exc)
                return "PORTAL_UNAVAILABLE"
            try:
                # Before trusting an empty list, establish whether this
                # session is even authenticated. An expired session that
                # has been redirected to a login page produces exactly the
                # same "no category links" as a genuinely quiet account,
                # and reporting that as NO_CATEGORIES tells the employee
                # everything is fine while their notifications silently
                # stop.
                state = await discovery.observe_session_state()
                _report_session_state(session_observer, account_id, state)
                if state == "LOGGED_OUT":
                    return _mark_reconnect_required(conn, account_id, vault_dir)
                if state != "AUTHENTICATED":
                    # Cannot tell. Revoking a session on a guess would
                    # force a pointless re-login for what may be a network
                    # blip, so nothing is changed.
                    _log_unavailable("session state before discovery", state=state)
                    return "PORTAL_UNAVAILABLE"

                codes = await discovery.discover_notification_categories()

                if not codes:
                    # Re-checked, because the session can expire between
                    # opening the landing page and reading the alert list
                    # -- which is precisely when an empty result is most
                    # misleading.
                    state = await discovery.observe_session_state()
                    _report_session_state(session_observer, account_id, state)
                    if state == "LOGGED_OUT":
                        return _mark_reconnect_required(conn, account_id, vault_dir)
                    if state != "AUTHENTICATED":
                        _log_unavailable("session state after empty discovery", state=state)
                        return "PORTAL_UNAVAILABLE"
            except Exception as exc:
                # A failure reading the surface is NOT evidence that the
                # session expired: revoking here would log the employee
                # out because the network hiccupped.
                _log_unavailable("category discovery failed", exc=exc)
                return "PORTAL_UNAVAILABLE"
            finally:
                await _close_reader_safely(discovery, "discovery reader")

        if not codes:
            # An authenticated account with genuinely no open alerts.
            # Still NOT "every alert is gone": nothing was read, so
            # run_poll is never called and no presence lifecycle advances
            # on this evidence.
            return "NO_CATEGORIES"

        try:
            reader = await open_reader(
                browser, lease, notification_contracts(allowed_host, codes, entity),
                allowed_host, context_options={"storage_state": storage_state},
                portal_base=base,
            )
        except Exception as exc:
            _log_unavailable("notification reader could not open", exc=exc)
            return "PORTAL_UNAVAILABLE"

        try:
            # poll_run_categories.category_code is a foreign key into
            # categories(code_alerte), and the categories table ships
            # empty because no reviewed fixed list exists -- the codes are
            # whatever this account's portal currently offers. Registering
            # the discovered codes first is what keeps run_poll from
            # failing on an IntegrityError after the reads already
            # succeeded.
            #
            # The code is used as its own label: discovery deliberately
            # returns codes and nothing else (a portal-supplied title is
            # not something to store unreviewed), so there is no truthful
            # label to record and a code is at least accurate.
            categories = CategoriesRepository(conn)
            for code in codes:
                categories.ensure(code, code)

            version = AccountStateVersionRepository(conn).bump(account_id)
            _poll_run_id, run_status = await run_poll(conn, account_id, reader, codes, version)
            if run_status == "COMPLETE":
                return "POLLED"
            # Reaching run_poll is not the same as reading anything. A run
            # whose every category FAILED was still reported as POLLED,
            # and the employee was told "Notifications actualisées." after
            # a refresh that read nothing at all.
            logger.warning("notification poll finished with status=%s", run_status)
            return "POLL_INCOMPLETE" if run_status == "PARTIAL" else "POLL_FAILED"
        finally:
            await _close_reader_safely(reader, "reader")
    finally:
        lease.release()


def _report_session_state(observer, account_id: str, state: str) -> None:
    """Hands one observed session state to whoever is watching.

    A callback rather than an import: this layer must not know about
    mcma.app, and the observation is the only thing worth sharing --
    never the reader, the page or the session material. An observer that
    raises must not fail a poll that otherwise worked.
    """
    if observer is None:
        return
    try:
        observer(account_id, state)
    except Exception:
        logger.warning("the session-state observer raised; the poll is unaffected", exc_info=True)


def _log_unavailable(stage: str, *, exc: BaseException | None = None, state: str | None = None) -> None:
    """Names the branch a PORTAL_UNAVAILABLE came from.

    Five exits produced that one outcome with no trace of which, so a
    refresh that failed before run_poll left nothing to distinguish "the
    browser did not open" from "the session probe could not decide" from
    "discovery threw". The exception TYPE is logged and its message is
    not: a portal failure page can carry the employee's username, and the
    type is what tells an operator what happened."""
    if exc is not None:
        logger.warning("notification poll unavailable at %s: %s", stage, type(exc).__name__)
    else:
        logger.warning("notification poll unavailable at %s: state=%s", stage, state)


async def _close_reader_safely(reader, stage: str) -> None:
    """Tears a read capability down without letting the teardown decide
    the outcome of the poll.

    A `finally: await reader.close()` runs BEFORE the `return` it is
    unwinding completes, so a browser that fails to close replaces an
    already-determined result with its own exception: a refresh that read
    the notifications, persisted the claims and released the lease was
    reported to the employee as HTTP 502 REFRESH_FAILED_ValueError. The
    close is still attempted, and a failure is still visible to an
    operator -- it just no longer overwrites work that succeeded.

    Only the exception TYPE is logged, for the same reason as
    _log_unavailable: a teardown failure can carry a URL, page content or
    session material in its message, and the type is what an operator
    needs. Exception, not BaseException, so cancellation still
    propagates."""
    try:
        await reader.close()
    except Exception as exc:
        logger.warning("notification %s cleanup failed: %s", stage, type(exc).__name__)


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
    session_observer=None,
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
                session_observer=session_observer,
            )
        except Exception as exc:  # pragma: no cover - defensive isolation only
            # One account's unexpected failure must never stop the others.
            outcomes[account.account_id] = f"ERROR_{type(exc).__name__}"
    return outcomes
