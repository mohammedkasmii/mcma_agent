"""mcma.app.workstation_runner.browser_gate -- ONE shared, non-blocking
mutual-exclusion gate for every visible/headless browser operation this
runner performs: the saved-session worker (manual MCMA login +
verification), the dossier job worker, and the central notification
onboarding worker. At most one owner holds it at any instant, so two
competing browser windows can never exist.

Deliberately non-blocking and owner-checked: `try_acquire` never waits
(a caller that loses simply does not start -- it is never queued behind a
possibly-unbounded human login), and `release` is a no-op unless the caller
is the current holder, so a late/duplicate release can never free someone
else's hold. Pure stdlib; no browser, portal, HTTP or Tk code here."""

from __future__ import annotations

import threading

OWNER_SESSION = "SESSION_WORKER"
OWNER_JOB = "JOB_WORKER"
OWNER_ONBOARDING = "NOTIFICATION_ONBOARDING"

_OWNERS = frozenset({OWNER_SESSION, OWNER_JOB, OWNER_ONBOARDING})


class BrowserOperationGate:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._holder: str | None = None

    def try_acquire(self, owner: str) -> bool:
        if owner not in _OWNERS:
            raise ValueError("unknown gate owner")
        with self._lock:
            if self._holder is not None:
                return False
            self._holder = owner
            return True

    def release(self, owner: str) -> None:
        with self._lock:
            if self._holder == owner:
                self._holder = None

    def holder(self) -> str | None:
        with self._lock:
            return self._holder

    def is_busy(self) -> bool:
        return self.holder() is not None
