"""
mcma.execution.lease -- threads a real per-account LeaseHandle from
persistence into portal capabilities (INC-11, WORKFLOW_STATE_MODEL.md §3).

`execution` acquires the lease THROUGH `persistence` and hands the
resulting handle to `portal` (open_reader/open_verified_writer's
`lease_handle` parameter) -- `portal` never reacquires the lock and never
imports sqlite3/persistence itself (the import-linter contract forbids
it). This module is the one seam that legitimately imports both.
"""

from __future__ import annotations

import uuid

from mcma.persistence.leases import AccountLeaseHandle, DEFAULT_LEASE_TTL_SECONDS, acquire_lease


def new_instance_id() -> str:
    """One id per running process -- stable identity for owner_instance_id,
    never derived from anything portal-observable."""
    return uuid.uuid4().hex


def acquire_account_lease(
    conn,  # sqlite3.Connection -- left unannotated: mcma.persistence is the
    # sole permitted importer of sqlite3 (import-linter contract); even a
    # TYPE_CHECKING-only import of it here would still count as a direct
    # forbidden edge (import-linter parses import statements regardless of
    # runtime guards).
    account_id: str,
    instance_id: str,
    *,
    owner_job_id: str | None = None,
    ttl_seconds: int = DEFAULT_LEASE_TTL_SECONDS,
) -> AccountLeaseHandle:
    """Acquired at ACQUIRING_ACCOUNT_LOCK, held through IDENTITY_VERIFYING
    -> WRITING -> VERIFYING, released on entry to READY_FOR_HUMAN_REVIEW
    (or any terminal/abort outcome) -- lease lifetime is the caller's
    (mcma.execution.jobs, INC-12) responsibility; this function only
    performs the acquire step."""
    return acquire_lease(conn, account_id, instance_id, owner_job_id=owner_job_id, ttl_seconds=ttl_seconds)
