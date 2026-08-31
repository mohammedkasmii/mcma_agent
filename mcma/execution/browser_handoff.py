"""
mcma.execution.browser_handoff -- the in-memory active-review-session
registry (correction batch / owner amendment, single-process pilot).

Maps job_id -> an opaque, duck-typed browser/page/context handle for THIS
running process's currently-open human-review browsers. This module never
imports mcma.portal or Playwright itself -- it only needs a handle with a
`register_close_callback(fn)` method (a real guarded-context wrapper the
future job runner supplies, or a bare fake in tests); no Playwright object
is ever serialized or persisted here, only held in memory for the life of
the process.

Registry loss on restart is not a special case handled here: a process
restart means every entry is gone by construction (it was only ever
in-memory) -- mcma.execution.reconcile.reconcile_on_restart's own
fail-closed WRITING/VERIFYING/READY_FOR_HUMAN_REVIEW ->
INTERRUPTED_NEEDS_HUMAN_REVIEW handling is what covers that loss; this
module does not duplicate that logic, it only prevents a SECOND
concurrent session for the same shared account while the process is up.
"""

from __future__ import annotations

from typing import Callable, Dict, Optional, Protocol, runtime_checkable


@runtime_checkable
class BrowserHandle(Protocol):
    def register_close_callback(self, on_close: Callable[[], None]) -> None: ...


class DuplicateActiveReview(Exception):
    """No second form job may concurrently use the same shared portal
    account: registering a handle for an account_id that already has a
    DIFFERENT job's handle active raises this instead of silently
    replacing it (which would let two automated sessions race on one
    shared credential)."""


class ActiveReviewRegistry:
    """Not a singleton by design -- the caller (the still-to-be-wired job
    runner) owns exactly one instance for the process's lifetime and
    passes it explicitly; tests construct their own throwaway instances."""

    def __init__(self) -> None:
        self._handle_by_job_id: Dict[str, BrowserHandle] = {}
        self._account_id_by_job_id: Dict[str, str] = {}
        self._job_id_by_account_id: Dict[str, str] = {}

    def register(
        self,
        job_id: str,
        account_id: str,
        handle: BrowserHandle,
        *,
        on_close: Callable[[str], None],
    ) -> None:
        existing_job_id = self._job_id_by_account_id.get(account_id)
        if existing_job_id is not None and existing_job_id != job_id:
            raise DuplicateActiveReview(
                f"account {account_id!r} already has an active review session for job {existing_job_id!r}"
            )
        self._handle_by_job_id[job_id] = handle
        self._account_id_by_job_id[job_id] = account_id
        self._job_id_by_account_id[account_id] = job_id
        handle.register_close_callback(lambda: self._on_handle_closed(job_id, on_close))

    def _on_handle_closed(self, job_id: str, on_close: Callable[[str], None]) -> None:
        self.unregister(job_id)
        on_close(job_id)

    def unregister(self, job_id: str) -> None:
        account_id = self._account_id_by_job_id.pop(job_id, None)
        self._handle_by_job_id.pop(job_id, None)
        if account_id is not None and self._job_id_by_account_id.get(account_id) == job_id:
            self._job_id_by_account_id.pop(account_id, None)

    def get(self, job_id: str) -> Optional[BrowserHandle]:
        return self._handle_by_job_id.get(job_id)

    def is_account_active(self, account_id: str) -> bool:
        return account_id in self._job_id_by_account_id

    def active_job_for_account(self, account_id: str) -> Optional[str]:
        """The job_id currently holding this account's review session, or
        None. Unlike is_account_active this lets a caller tell "some
        OTHER job has it" from "this same job already has it", which is
        what the runner needs to refuse a second same-account job BEFORE
        it creates a browser context rather than after it has already
        written (pilot-runner correction, requirement 4)."""
        return self._job_id_by_account_id.get(account_id)

    def active_job_count(self) -> int:
        return len(self._handle_by_job_id)
