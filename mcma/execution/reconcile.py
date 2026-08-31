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
        try:
            outcomes[job_id] = _reconcile_one(conn, row, status, encryptor)
        except Exception as exc:
            # Fable-review correction: a single corrupted/unexpected row
            # (e.g. a malformed expires_at that retrieve_and_verify_job_
            # input's datetime.fromisoformat() cannot parse, raising a
            # bare ValueError rather than a JobInputUnavailable subclass)
            # must never abort reconciliation for every OTHER job. This
            # outer boundary fails ONLY this job closed to ERROR and
            # continues -- it is a startup-robustness backstop, not a
            # substitute for the specific reason codes above.
            try:
                transition(conn, job_id, "ERROR", reason_code=f"RECONCILE_UNEXPECTED_{type(exc).__name__}")
            except Exception:
                pass
            outcomes[job_id] = "ERROR"

    return outcomes


def _reconcile_one(conn, row, status: str, encryptor) -> str:
    job_id = row["job_id"]

    if status in _RETURN_TO_QUEUED_STATUSES:
        try:
            retrieve_and_verify_job_input(conn, job_id, row["input_hash"], encryptor)
        except JobInputUnavailable as exc:
            transition(conn, job_id, "ERROR", reason_code=exc.reason_code)
            return "ERROR"
        transition(conn, job_id, "QUEUED")
        return "QUEUED"

    if status in _PRE_WRITE_ABORT_STATUSES:
        # Pre-write -- no row write has occurred yet, even in
        # IDENTITY_VERIFIED (the step immediately before WRITING).
        transition(conn, job_id, "ABORTED_ON_RESTART")
        _release_lease_for(conn, row["account_id"])
        return "ABORTED_ON_RESTART"

    if status in _INTERRUPTED_STATUSES:
        # Writes possibly partial -- never automatically resumed or
        # replayed.
        transition(conn, job_id, "INTERRUPTED_NEEDS_HUMAN_REVIEW")
        _release_lease_for(conn, row["account_id"])
        return "INTERRUPTED_NEEDS_HUMAN_REVIEW"

    # Unreachable given list_non_terminal()'s own terminal-status
    # exclusion, but fail closed rather than silently skip.
    transition(conn, job_id, "ERROR", reason_code="UNRECOGNIZED_RESTART_STATUS")
    return "ERROR"


def _release_lease_for(conn, account_id: str) -> None:
    conn.execute("DELETE FROM account_leases WHERE account_id = ?", (account_id,))
