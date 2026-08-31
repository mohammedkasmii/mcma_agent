"""
mcma.execution.reconcile -- deterministic restart reconciliation
(INC-12, WORKFLOW_STATE_MODEL.md §7). Runs once, before serving, over
every non-terminal `automation_jobs` row. Every branch below is an exact,
config-independent outcome -- no non-terminal status is left without a
deterministic, fail-closed result (coverage matches DATA_MODEL.md §4's
full status CHECK).
"""

from __future__ import annotations

from mcma.execution.inputs import JobInputUnavailable, retrieve_and_verify_job_input
from mcma.execution.jobs import transition
from mcma.persistence.leases import release_stale_leases
from mcma.persistence.repositories.jobs import AutomationJobsRepository

_RETURN_TO_QUEUED_STATUSES = frozenset({"QUEUED", "PLANNING", "PLANNED", "READ_ONLY_IDENTITY_CHECK"})
_PRE_WRITE_ABORT_STATUSES = frozenset({"ACQUIRING_ACCOUNT_LOCK", "IDENTITY_VERIFYING", "IDENTITY_VERIFIED"})
_INTERRUPTED_STATUSES = frozenset({"WRITING", "VERIFYING"})


def reconcile_on_restart(conn, *, encryptor) -> dict:
    """Returns a summary dict of {job_id: outcome_status} for every
    non-terminal job processed. Releases stale account_leases FIRST."""
    release_stale_leases(conn)

    outcomes: dict = {}
    jobs_repo = AutomationJobsRepository(conn)
    for row in jobs_repo.list_non_terminal():
        job_id = row["job_id"]
        status = row["status"]

        if status in _RETURN_TO_QUEUED_STATUSES:
            try:
                retrieve_and_verify_job_input(conn, job_id, row["input_hash"], encryptor)
            except JobInputUnavailable as exc:
                transition(conn, job_id, "ERROR", reason_code=exc.reason_code)
                outcomes[job_id] = "ERROR"
                continue
            transition(conn, job_id, "QUEUED")
            outcomes[job_id] = "QUEUED"
            continue

        if status in _PRE_WRITE_ABORT_STATUSES:
            # Pre-write -- no row write has occurred yet, even in
            # IDENTITY_VERIFIED (the step immediately before WRITING).
            transition(conn, job_id, "ABORTED_ON_RESTART")
            _release_lease_for(conn, row["account_id"])
            outcomes[job_id] = "ABORTED_ON_RESTART"
            continue

        if status in _INTERRUPTED_STATUSES:
            # Writes possibly partial -- never automatically resumed or
            # replayed.
            transition(conn, job_id, "INTERRUPTED_NEEDS_HUMAN_REVIEW")
            _release_lease_for(conn, row["account_id"])
            outcomes[job_id] = "INTERRUPTED_NEEDS_HUMAN_REVIEW"
            continue

        # Unreachable given list_non_terminal()'s own terminal-status
        # exclusion, but fail closed rather than silently skip.
        transition(conn, job_id, "ERROR", reason_code="UNRECOGNIZED_RESTART_STATUS")
        outcomes[job_id] = "ERROR"

    return outcomes


def _release_lease_for(conn, account_id: str) -> None:
    conn.execute("DELETE FROM account_leases WHERE account_id = ?", (account_id,))
