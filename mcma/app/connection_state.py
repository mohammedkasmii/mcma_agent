"""
mcma.app.connection_state -- what this process has actually OBSERVED about
each account's portal session.

WHY THIS EXISTS. GET /accounts used to report CONNECTED whenever a
portal_sessions row said ACTIVE. Nothing ages that row out and only an
explicit revoke clears it, so an account signed in yesterday still showed
"Connecté" and offered "Actualiser" this morning -- and the refresh then
failed. The interface was asserting a fact nobody had checked.

Persisted session material tells us a session EXISTS, not that it works.
Those are different claims and this module keeps them apart: the database
answers "is there material, and was it revoked", and this tracker answers
"has this process seen evidence it is live".

DELIBERATELY IN MEMORY, and deliberately not a migration. The question it
answers is about the current process: a state carried across a restart
would be exactly the stale assertion being removed here. A fresh process
starts knowing nothing, which is why stored ACTIVE material begins as
UNVERIFIED rather than CONNECTED.

NOT a second copy of server state. Nothing here duplicates a column;
these observations have no home in the schema, and the account list is
still read from the database on every request.

Also deliberately NOT derived from poll_runs. Several poll exits return
early without writing a poll_run at all, so yesterday's COMPLETE row can
remain the latest one indefinitely while today's session is dead --
reproducing the same stale claim through a different route.
"""

from __future__ import annotations

import threading

# The four states the employee interface distinguishes. Kept as plain
# strings because they cross the HTTP boundary verbatim.
CONNECTED = "CONNECTED"
UNVERIFIED = "UNVERIFIED"
RECONNECT_REQUIRED = "RECONNECT_REQUIRED"
NOT_CONNECTED = "NOT_CONNECTED"


class ConnectionStateTracker:
    """Live, per-account observations. Nothing global: one account's
    evidence never speaks for another."""

    def __init__(self) -> None:
        self._verified: set[str] = set()
        # Read from request handlers on worker threads while the poll loop
        # writes from the event loop.
        self._lock = threading.Lock()

    def mark_authenticated(self, account_id: str) -> None:
        """Positive evidence: a probe saw an authenticated page, or a
        manual login completed. capture_session_for_account only returns
        after perform_manual_login() has positively observed the logged-in
        markers, so a completed login is evidence, not an assumption."""
        with self._lock:
            self._verified.add(account_id)

    def mark_unverified(self, account_id: str) -> None:
        """We looked and could not tell. The session is NOT revoked on
        this: an indeterminate page may be a network blip, and forcing a
        pointless OTP is a real cost to push onto an employee for our own
        uncertainty."""
        with self._lock:
            self._verified.discard(account_id)

    def mark_logged_out(self, account_id: str) -> None:
        """Positive evidence of a dead session. The revoke itself stays
        where it already lives (the poller writes the database); this only
        drops the live observation."""
        with self._lock:
            self._verified.discard(account_id)

    def forget(self, account_id: str) -> None:
        with self._lock:
            self._verified.discard(account_id)

    def is_verified(self, account_id: str) -> bool:
        with self._lock:
            return account_id in self._verified


def resolve_connection_state(
    *, has_active_session: bool, has_session_history: bool, verified_live: bool
) -> str:
    """The one place the four states are decided.

    `has_active_session` and `has_session_history` come from the database;
    `verified_live` from the tracker. Note the ordering: ACTIVE material
    plus no live evidence is UNVERIFIED, never CONNECTED. That single line
    is the bug this whole module exists to prevent.
    """
    if has_active_session:
        return CONNECTED if verified_live else UNVERIFIED
    if has_session_history:
        # Material existed and was revoked or replaced: this account was
        # connected once and needs signing in again -- a different thing
        # to tell someone than "never connected".
        return RECONNECT_REQUIRED
    return NOT_CONNECTED
