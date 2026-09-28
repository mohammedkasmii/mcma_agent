"""mcma.app.workstation_runner.sessions -- pure, thread-safe per-account
workstation MCMA session state (Phase 1B-B). No Playwright, no portal, no
sqlite3, no fastapi, no httpx: every transition here is driven by an
explicit call from the composition root (mcma.app.workstation_runner.app)
or the controller, never by this module reaching out on its own.

Wire protocol note: the server only understands four session states
(mcma.app.workstation_runner.protocol.SESSION_STATES). PENDING_VERIFICATION
is a fifth, LOCAL-ONLY state for "a session file exists but has not yet
been positively re-verified this run" -- it is never sent on the wire.
heartbeat_sessions() simply omits such an account, which the server's own
registry.heartbeat() treats identically to NOT_CONFIGURED (a missing
account_id in the reported list clears any previously-stored capability
row for it) -- exactly the safe reading: nothing may be dispatched to an
account whose readiness has not been positively proven THIS run."""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable

from mcma.app.workstation_runner.protocol import RUNNER_ACCOUNT_IDS, SESSION_STATES

assert set(SESSION_STATES) == {"NOT_CONFIGURED", "LOGIN_REQUIRED", "READY", "ERROR"}, (
    "sessions.py's wire-state mapping has drifted from protocol.SESSION_STATES"
)


class ProbeOutcome(Enum):
    """The result of mcma.portal.workstation_sessions.verify_saved_session
    (or an exception from it, mapped to ERROR by the caller)."""

    AUTHENTICATED = "AUTHENTICATED"
    LOGGED_OUT = "LOGGED_OUT"
    INDETERMINATE = "INDETERMINATE"
    ERROR = "ERROR"


class AccountState(Enum):
    NOT_CONFIGURED = "NOT_CONFIGURED"
    PENDING_VERIFICATION = "PENDING_VERIFICATION"  # local only, never on the wire
    LOGIN_REQUIRED = "LOGIN_REQUIRED"
    READY = "READY"
    ERROR = "ERROR"


_WIRE_STATE: dict[AccountState, str | None] = {
    AccountState.NOT_CONFIGURED: None,
    AccountState.PENDING_VERIFICATION: None,
    AccountState.LOGIN_REQUIRED: "LOGIN_REQUIRED",
    AccountState.READY: "READY",
    AccountState.ERROR: "ERROR",
}


@dataclass(frozen=True)
class AccountView:
    account_id: str
    state: AccountState


@dataclass(frozen=True)
class ReconciliationResult:
    """What changed after reconcile_allowed_accounts() -- the caller uses
    this to cancel/purge removed accounts and to enqueue verification for
    newly-tracked ones with an existing saved session."""

    removed: tuple[str, ...]
    added_needing_verification: tuple[str, ...]


class WorkstationSessionManager:
    """Tracks state for exactly the accounts the SERVER most recently
    confirmed are authorized -- nothing is tracked (and nothing is ever
    reported) before the first successful reconciliation, which is what
    makes the very first heartbeat's sessions:[] happen for free (see
    heartbeat_sessions() on an empty manager)."""

    def __init__(self, *, has_saved_session: Callable[[str], bool]) -> None:
        self._has_saved_session = has_saved_session
        self._lock = threading.Lock()
        self._states: dict[str, AccountState] = {}

    def reconcile_allowed_accounts(self, allowed_account_ids) -> ReconciliationResult:
        # dict.fromkeys dedupes while preserving first-occurrence order -- the
        # server sending the same account_id twice in one heartbeat response
        # must never enqueue two VERIFY commands or otherwise be treated
        # differently from sending it once.
        allowed = tuple(dict.fromkeys(a for a in allowed_account_ids if a in RUNNER_ACCOUNT_IDS))
        with self._lock:
            removed = tuple(a for a in self._states if a not in allowed)
            added = tuple(a for a in allowed if a not in self._states)
            for account_id in removed:
                del self._states[account_id]
            needing_verification = []
            for account_id in added:
                if self._has_saved_session(account_id):
                    self._states[account_id] = AccountState.PENDING_VERIFICATION
                    needing_verification.append(account_id)
                else:
                    self._states[account_id] = AccountState.NOT_CONFIGURED
        return ReconciliationResult(removed=removed, added_needing_verification=tuple(needing_verification))

    def reset(self) -> None:
        """Drops every tracked account (used on runner revocation). The
        caller is separately responsible for clearing on-disk sessions and
        cancelling any in-flight browser work."""
        with self._lock:
            self._states.clear()

    def record_probe_outcome(self, account_id: str, outcome: ProbeOutcome) -> bool:
        """Returns True iff the account was still tracked (authorized) at
        the exact moment of this call and the transition was applied.
        Callers (browser_worker.py) MUST gate any update callback on this
        return value rather than a separate earlier is_authorized() check
        -- checking first and mutating a moment later leaves a window
        where the account could be removed in between, letting a stale
        result emit a callback for an account no longer tracked at all.
        Collapsing the check-and-set into one atomic, lock-protected
        operation closes that window entirely."""
        with self._lock:
            if account_id not in self._states:
                return False  # no longer authorized -- a stale in-flight probe result is ignored
            if outcome is ProbeOutcome.AUTHENTICATED:
                self._states[account_id] = AccountState.READY
            elif outcome is ProbeOutcome.LOGGED_OUT:
                self._states[account_id] = AccountState.LOGIN_REQUIRED
            else:
                self._states[account_id] = AccountState.ERROR
            return True

    def record_login_success(self, account_id: str) -> bool:
        """Call ONLY after the new session has already been positively
        authenticated AND durably persisted -- ordering is the caller's
        (browser_worker.py's) responsibility; this method itself performs
        no I/O and does no ordering enforcement. Returns True iff the
        account was still tracked and the transition was applied (see
        record_probe_outcome's docstring for why the caller must gate its
        update callback on this return value)."""
        with self._lock:
            if account_id not in self._states:
                return False
            self._states[account_id] = AccountState.READY
            return True

    def record_operation_error(self, account_id: str) -> bool:
        """A narrow, explicit ERROR transition for an operational failure
        that is NOT itself a portal probe result -- e.g. a positively-
        authenticated login whose subsequent encrypted-store save fails, or
        a LOGGED_OUT verification whose store.clear() itself fails. Kept
        separate from record_probe_outcome (which is documented as "the
        result of verify_saved_session, or an exception from it") so a
        login-side or clear-side failure is never confused with a portal
        probe outcome. Returns True iff the account was still tracked and
        the transition was applied -- a stale result must never
        restore/resurrect a removed account, nor emit a callback for one."""
        with self._lock:
            if account_id not in self._states:
                return False
            self._states[account_id] = AccountState.ERROR
            return True

    def record_missing_saved_session(self, account_id: str) -> bool:
        """Positive evidence, discovered BEFORE any browser launch, that no
        valid saved session exists for this account -- the file is missing,
        or failed to decrypt/validate (session_store.load() already treats
        both identically, returning None for either -- see its own
        docstring). The truthful state is NOT_CONFIGURED, never a stale
        READY/LOGIN_REQUIRED/ERROR left over from before. Returns True iff
        the account was still tracked and the transition was applied."""
        with self._lock:
            if account_id not in self._states:
                return False
            self._states[account_id] = AccountState.NOT_CONFIGURED
            return True

    def state_of(self, account_id: str) -> AccountState | None:
        with self._lock:
            return self._states.get(account_id)

    def is_authorized(self, account_id: str) -> bool:
        with self._lock:
            return account_id in self._states

    def tracked_account_ids(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._states)

    def snapshot(self) -> tuple[AccountView, ...]:
        with self._lock:
            return tuple(AccountView(a, s) for a, s in sorted(self._states.items()))

    def heartbeat_sessions(self) -> tuple[dict, ...]:
        with self._lock:
            items = [
                {"account_id": account_id, "state": wire}
                for account_id, state in self._states.items()
                if (wire := _WIRE_STATE[state]) is not None
            ]
        return tuple(sorted(items, key=lambda item: item["account_id"]))


DEFAULT_VERIFICATION_INTERVAL_SECONDS = 300.0


class VerificationScheduler:
    """Approximately-every-5-minutes background verification policy. Driven
    by an external tick (the controller calling due_accounts() on every
    successful heartbeat) rather than owning a second timer thread -- and
    made testable without real waiting via an injectable monotonic clock."""

    def __init__(
        self, *, interval_seconds: float = DEFAULT_VERIFICATION_INTERVAL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if (
            isinstance(interval_seconds, bool)
            or not isinstance(interval_seconds, (int, float))
            or not math.isfinite(interval_seconds)
            or interval_seconds <= 0
        ):
            raise ValueError("interval_seconds must be a finite number greater than zero")
        self._interval = float(interval_seconds)
        self._clock = clock
        self._lock = threading.Lock()
        self._last_verified_at: dict[str, float] = {}

    def mark_verified(self, account_id: str) -> None:
        """Call this the moment a verification is DECIDED/enqueued for
        `account_id` (not only on completion) -- it is what prevents
        due_accounts() from re-triggering the same account on every tick
        while a probe is still in flight."""
        with self._lock:
            self._last_verified_at[account_id] = self._clock()

    def forget(self, account_id: str) -> None:
        with self._lock:
            self._last_verified_at.pop(account_id, None)

    def due_accounts(self, tracked_account_ids) -> tuple[str, ...]:
        now = self._clock()
        with self._lock:
            return tuple(
                account_id for account_id in tracked_account_ids
                if (last := self._last_verified_at.get(account_id)) is None or (now - last) >= self._interval
            )
