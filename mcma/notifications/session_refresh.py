"""
mcma.notifications.session_refresh -- the scheduled session-refresh
poller (INC-14, review TR-F31), replacing the baseline's unscheduled,
no-escalation session keep-alive daemon. Runs under the per-account
lease (INC-11) and escalates via an injected callback after repeated
failure -- the real health/observability wiring (INC-20) provides the
callback in production; this module never imports it directly.
"""

from __future__ import annotations

from typing import Callable

from mcma.persistence.leases import acquire_lease

ESCALATE_AFTER_CONSECUTIVE_FAILURES = 3


def refresh_account_session(
    conn,
    account_id: str,
    instance_id: str,
    *,
    refresh_check: Callable[[], bool],
    escalate: Callable[[str, int], None],
    consecutive_failures: int = 0,
) -> int:
    """Acquires the account's lease (never operates without one -- a
    session refresh IS an account-scoped operation), runs refresh_check()
    once, and returns the updated consecutive-failure count. Calls
    escalate(account_id, count) once the threshold is reached or
    exceeded, on every such call (not just the first) -- a caller may
    choose to de-duplicate escalation notices itself."""
    lease = acquire_lease(conn, account_id, instance_id)
    try:
        try:
            ok = bool(refresh_check())
        except Exception:
            ok = False

        if ok:
            return 0

        new_count = consecutive_failures + 1
        if new_count >= ESCALATE_AFTER_CONSECUTIVE_FAILURES:
            escalate(account_id, new_count)
        return new_count
    finally:
        lease.release()
