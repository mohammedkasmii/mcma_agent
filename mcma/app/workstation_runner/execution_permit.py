"""mcma.app.workstation_runner.execution_permit -- a thread-safe,
fail-closed execution-permit abstraction for the workstation EXECUTE write
path (Phase 1C-C Pass 2A, item B).

Lightweight-package rule (tests/app/workstation_runner/
test_import_isolation.py): this module imports nothing beyond the
standard library. It never imports mcma.portal and knows nothing about
Playwright, VerifiedMissionWriter, or any portal exception -- it is a
plain, structural stand-in for mcma.portal.capabilities.LeaseHandle (an
account_id attribute plus an async assert_valid() method) that the
composition root (mcma.app.workstation_runner.app, the one module allowed
to import mcma.portal) can hand directly to
mcma.portal.workstation_execute.run_workstation_execute_write as its
`permit` argument -- VerifiedMissionWriter's own construction-time and
per-mutation lease checks (writer.py's `_recheck_lease`) call
`assert_valid()` on whatever it is given without ever needing to import
this class.

One-way ratchet: a permit starts INVALID. `activate()` -- called exactly
once, after the server has accepted start_job() -- makes it valid.
`invalidate()` makes it permanently invalid; nothing after that call can
ever make it valid again, including a later activate() call (a stale
activation racing a shutdown/renewal-failure/cancellation must never win).
Every state read/write goes through one lock, since renewal failure is
observed on the event-loop thread but a future caller (application
shutdown, an operator cancel) could reasonably invalidate from a different
thread.

Carries only the account_id -- never a claim_token, runner_secret, or any
other server-issued credential (requirement B: "no server secret or
claimant information")."""

from __future__ import annotations

import threading


class ExecutionPermitInvalid(Exception):
    """Raised by assert_valid() when the permit is not currently valid --
    either never activated, or permanently invalidated. Carries only the
    account_id, never a reason string that might embed anything sensitive."""

    def __init__(self, account_id: str) -> None:
        super().__init__(f"execution permit for account {account_id!r} is not valid")
        self.account_id = account_id


class ExecutionPermit:
    """Structurally compatible with mcma.portal.capabilities.LeaseHandle
    (account_id + async assert_valid()) without importing it."""

    __slots__ = ("_account_id", "_lock", "_valid", "_permanently_invalid")

    def __init__(self, account_id: str) -> None:
        self._account_id = account_id
        self._lock = threading.Lock()
        self._valid = False
        self._permanently_invalid = False

    @property
    def account_id(self) -> str:
        return self._account_id

    def activate(self) -> None:
        """Makes the permit valid -- but only if it has not already been
        permanently invalidated. Safe to call more than once (idempotent);
        never reverses an invalidate() that already happened, regardless
        of call order (a start_job response that arrives after a shutdown
        signal must never resurrect the permit)."""
        with self._lock:
            if not self._permanently_invalid:
                self._valid = True

    def invalidate(self) -> None:
        """Permanently invalidates the permit. One-way: no future call to
        activate() can ever undo this. Safe to call more than once and
        from any thread."""
        with self._lock:
            self._valid = False
            self._permanently_invalid = True

    @property
    def is_valid(self) -> bool:
        with self._lock:
            return self._valid

    async def assert_valid(self) -> None:
        """Matches mcma.portal.capabilities.LeaseHandle's own
        assert_valid() shape exactly, so VerifiedMissionWriter's existing
        lease-recheck calls (before every mutation, and again after) work
        against this permit with no portal-side change at all."""
        if not self.is_valid:
            raise ExecutionPermitInvalid(self._account_id)
