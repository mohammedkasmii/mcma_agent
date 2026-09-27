"""
mcma.app.server_status -- the operator-facing status vocabulary of the
central server, kept apart from the API module so the rules are one small
pure function that is easy to test and easy to read.

Health answers "what is the state of each component"; readiness answers
"should traffic be sent here". They differ on purpose:

  * The database and configuration are initialised BEFORE the listener
    opens, so by the time anything can ask, they are either fine or the
    process never started.
  * A notification browser that is starting or degraded does NOT make the
    server unready. Employee authentication, notes and audit history stay
    correct and useful without it, the poller retries on its own schedule,
    and taking the whole application out of rotation for a Chromium
    problem would be worse than serving it and saying so. The degraded
    state is reported prominently instead, for operators to alert on.
  * A server that has begun shutting down is never ready.

Nothing here carries an exception message, a path or session material --
only enumerated states.
"""

from __future__ import annotations

from typing import Callable, TypedDict


class ServerState(TypedDict):
    notifications: str      # NotificationServiceState value
    shutting_down: bool


ServerStateProvider = Callable[[], ServerState]


def overall_status(db_ok: bool, notifications: str, shutting_down: bool) -> str:
    if shutting_down:
        return "shutting_down"
    if not db_ok:
        return "degraded"
    if notifications == "starting":
        return "starting"
    if notifications in ("degraded", "stopping", "stopped"):
        return "degraded"
    return "ok"


def is_ready(db_ok: bool, shutting_down: bool) -> bool:
    return db_ok and not shutting_down
