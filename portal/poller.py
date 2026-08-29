"""
portal/poller.py — Scheduled Multi-Account Poller
==================================================
Background task that refreshes every enabled account's alerts on a fixed
interval, inside the operating window only.

Implements PROJECT_ARCHITECTURE_BLUEPRINT.md §5, §8 and §10:

  - Runs 07:45–18:00 on configured days. Outside the window it does nothing at
    all: no authentication, no claim writes, no lifecycle changes.
  - One asyncio.Lock per account_id. The poller, an OTP login and (later) a
    filling job can never drive the same session concurrently.
  - One browser context per poll cycle, not one per HTTP request. This is what
    removes the "five employees clicking Actualiser spawns five Chromiums"
    problem from the old on-demand endpoint.
  - Lifecycle reconciliation is per CATEGORY and only for categories that
    actually answered (§8.2).
"""

import asyncio
import os
import sys
from datetime import datetime
from typing import Dict, Optional

from core.accounts import resolve_auth_state_path, DEFAULT_ACCOUNT_ID
from core.config import DASHBOARD_URL
from core.window import WINDOW
from db.repository import Repository
from portal.extractor import poll_account, FAILED

_locks: Dict[str, asyncio.Lock] = {}


def account_lock(account_id: str) -> asyncio.Lock:
    """One lock per account, created on first use."""
    if account_id not in _locks:
        _locks[account_id] = asyncio.Lock()
    return _locks[account_id]


def _log(msg: str) -> None:
    stamp = datetime.now().strftime("%H:%M:%S")
    try:
        print(f"[{stamp}] [poller] {msg}")
    except Exception:
        pass


async def poll_one_account(repo: Repository, account_id: str) -> dict:
    """
    Polls a single account and reconciles its claims.

    Returns a summary dict. Never raises: a failing account must not stop the
    others, and a failed poll must leave lifecycle state untouched.
    """
    from playwright.async_api import async_playwright

    auth_path = resolve_auth_state_path(account_id)
    if not auth_path:
        repo.set_session_health(account_id, "NEVER_AUTHENTICATED",
                                error="Aucune session enregistrée.")
        return {"account_id": account_id, "outcome": "AUTH_FAILED",
                "error": "no session file"}

    async with account_lock(account_id):
        run_id = repo.start_poll_run(account_id)
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context(storage_state=auth_path)
                page = await context.new_page()
                try:
                    result = await poll_account(page, account_id, DASHBOARD_URL)
                    # Persist any refreshed cookies so the session lives as long
                    # as possible before the next manual OTP login.
                    if result.outcome in ("SUCCESS", "PARTIAL"):
                        try:
                            await context.storage_state(path=auth_path)
                        except Exception:
                            pass
                finally:
                    await browser.close()

            if result.outcome in ("AUTH_FAILED", "UNREACHABLE"):
                repo.set_session_health(
                    account_id,
                    "EXPIRED" if result.outcome == "AUTH_FAILED" else "UNKNOWN",
                    error=result.error,
                )
                repo.finish_poll_run(run_id, result.outcome, error=result.error)
                _log(f"{account_id}: {result.outcome} — {result.error}")
                return {"account_id": account_id, "outcome": result.outcome,
                        "error": result.error}

            # Ingest, then reconcile — per category, and only where the portal
            # actually answered.
            new_total = 0
            for cat in result.categories:
                repo.record_category_outcome(
                    run_id, cat.code, cat.name, cat.outcome,
                    alerts_seen=len(cat.items), error=cat.error,
                )
                if cat.outcome == FAILED:
                    _log(f"{account_id}: category '{cat.name}' FAILED — "
                         f"skipping reconciliation for it ({cat.error})")
                    continue

                new, _seen = repo.upsert_claims_for_category(
                    account_id, cat.code, cat.name, cat.items
                )
                new_total += new
                repo.reconcile_category(
                    account_id, cat.code, [i.get("reference", "") for i in cat.items]
                )

            repo.set_session_health(account_id, "HEALTHY", validated=True)
            repo.finish_poll_run(run_id, result.outcome)

            failed = len(result.failed_categories)
            _log(f"{account_id}: {result.outcome} — {result.total_alerts} alerte(s), "
                 f"{new_total} nouvelle(s)" + (f", {failed} catégorie(s) en échec" if failed else ""))
            return {
                "account_id": account_id,
                "outcome": result.outcome,
                "total_alerts": result.total_alerts,
                "new_claims": new_total,
                "failed_categories": failed,
            }

        except Exception as e:
            repo.set_session_health(account_id, "UNKNOWN", error=str(e)[:300])
            repo.finish_poll_run(run_id, "UNREACHABLE", error=str(e)[:300])
            _log(f"{account_id}: exception — {e}")
            return {"account_id": account_id, "outcome": "UNREACHABLE", "error": str(e)}


async def poll_all_accounts(repo: Repository) -> list:
    """
    Polls every enabled account sequentially.

    Sequential on purpose: four concurrent Chromium instances on an office PC is
    exactly the resource problem this design removes.
    """
    results = []
    for acc in repo.list_accounts(only_enabled=True):
        account_id = acc["account_id"]
        if not resolve_auth_state_path(account_id):
            continue          # never authenticated; nothing to poll, no error
        results.append(await poll_one_account(repo, account_id))
    return results


async def poller_loop(repo: Repository, stop_event: Optional[asyncio.Event] = None) -> None:
    """
    The background scheduler. Ticks every minute, works only inside the window.

    A one-minute tick keeps the window boundaries sharp while the actual poll
    cadence stays at POLL_INTERVAL_MINUTES.
    """
    stop_event = stop_event or asyncio.Event()
    last_poll: Optional[datetime] = None
    announced_closed = False

    _log(f"démarré — fenêtre {WINDOW.start.strftime('%H:%M')}–"
         f"{WINDOW.end.strftime('%H:%M')} ({WINDOW.poll_interval_minutes} min), "
         f"fuseau {'FALLBACK UTC+1' if _tz_fallback() else 'Africa/Casablanca'}")

    while not stop_event.is_set():
        try:
            now = WINDOW.now()
            if not WINDOW.is_open(now):
                if not announced_closed:
                    _log("hors fenêtre — aucune interrogation du portail.")
                    announced_closed = True
                await _sleep_or_stop(stop_event, 60)
                continue

            announced_closed = False
            due = (
                last_poll is None
                or (now - last_poll).total_seconds() >= WINDOW.poll_interval_minutes * 60
            )
            if due:
                last_poll = now
                await poll_all_accounts(repo)

            await _sleep_or_stop(stop_event, 60)

        except asyncio.CancelledError:
            raise
        except Exception as e:
            _log(f"erreur inattendue dans la boucle : {e}")
            await _sleep_or_stop(stop_event, 60)

    _log("arrêté.")


def _tz_fallback() -> bool:
    from core.window import using_fallback_timezone
    return using_fallback_timezone()


async def _sleep_or_stop(stop_event: asyncio.Event, seconds: float) -> None:
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=seconds)
    except asyncio.TimeoutError:
        pass
