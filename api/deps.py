"""
api/deps.py — Shared Application State
=======================================
Holds the single Repository instance and the background poller task.

One repository per process: SQLite in WAL mode handles concurrent readers, and
all writes are serialised through this one connection plus SQLite's own locking.
"""

import asyncio
import contextlib
import os
from typing import Optional

from core.accounts import ACCOUNTS
from db.repository import Repository

_repo: Optional[Repository] = None
_poller_task: Optional[asyncio.Task] = None
_poller_stop: Optional[asyncio.Event] = None


def get_repo() -> Repository:
    """Lazily opens the database and seeds the account profiles."""
    global _repo
    if _repo is None:
        _repo = Repository()
        for acc in ACCOUNTS:
            _repo.upsert_account(
                account_id=acc["account_id"],
                entity=acc["entity"],
                portfolio=acc["portfolio"],
                display_name=acc["display_name"],
                base_url=acc["base_url"],
            )
    return _repo


def poller_disabled() -> bool:
    return os.environ.get("MCMA_DISABLE_POLLER", "").strip().lower() in {"1", "true", "yes"}


async def start_poller() -> None:
    global _poller_task, _poller_stop
    if poller_disabled():
        print("[i] Poller désactivé (MCMA_DISABLE_POLLER).")
        return
    from portal.poller import poller_loop
    _poller_stop = asyncio.Event()
    _poller_task = asyncio.create_task(poller_loop(get_repo(), _poller_stop))


async def stop_poller() -> None:
    global _poller_task, _poller_stop, _repo
    if _poller_stop is not None:
        _poller_stop.set()
    if _poller_task is not None:
        _poller_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await _poller_task
    _poller_task = None
    _poller_stop = None
    if _repo is not None:
        _repo.close()
        _repo = None
