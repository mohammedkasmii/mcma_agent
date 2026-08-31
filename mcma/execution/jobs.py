"""
mcma.execution.jobs -- atomic enqueue and the DRY_RUN/EXECUTE state
machines (INC-12, WORKFLOW_STATE_MODEL.md §2/§4, DATA_MODEL.md §4).

Two job kinds, two terminal paths, no upgrade: a DRY_RUN can never become
a write (no VerifiedMissionWriter is ever constructed for it -- the write
path structurally does not exist in run_dry_run_identity_check). An
EXECUTE job is separately authorized: it references its approved DRY_RUN
parent (same account_id AND workflow_name) and re-checks input_hash/
plan_hash before writing; any mismatch fails closed to ERROR/
INPUT_CHANGED, never executed on a guessed input.

Every orchestration function here takes injected callables for the
portal-facing steps (planning, identity checks, writing, native
calculation) -- this module never imports mcma.portal itself. Real
wiring (a genuine ReadCapability/VerifiedMissionWriter) is composed by
the caller (a future increment's job runner); tests inject stubs.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from mcma.execution.inputs import InputEncryptor, default_expiry
from mcma.persistence.repositories.jobs import AutomationJobsRepository, JobInputsRepository
from mcma.persistence.repositories.outbox import AccountStateVersionRepository, EventOutboxRepository

TERMINAL_STATUSES = frozenset(
    {
        "DRY_RUN_VERIFIED",
        "NEEDS_REVIEW",
        "IDENTITY_FAILED",
        "WRITE_ABORTED",
        "READY_FOR_HUMAN_REVIEW",
        "INTERRUPTED_NEEDS_HUMAN_REVIEW",
        "ABORTED_ON_RESTART",
        "ERROR",
    }
)


class JobAuthorizationError(Exception):
    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------- #
# Atomic enqueue (correction #5 / DATA_MODEL.md §4)
# --------------------------------------------------------------------- #


def _enqueue(
    conn,
    *,
    account_id: str,
    requested_by_user_id: str,
    workflow_name: str,
    mode: str,
    input_hash: str,
    typed_input_bytes: bytes,
    idempotency_key: str,
    encryptor: InputEncryptor,
    parent_job_id: Optional[str] = None,
    pii_class: str = "CONTAINS_PII",
    ttl_days: int = 30,
) -> str:
    jobs_repo = AutomationJobsRepository(conn)
    existing = jobs_repo.get_by_idempotency_key(account_id, idempotency_key)
    if existing is not None:
        return existing["job_id"]  # idempotent resubmit -- never silently re-run

    job_id = uuid.uuid4().hex
    now_dt = datetime.now(timezone.utc)
    now = now_dt.isoformat()

    conn.execute("BEGIN IMMEDIATE")
    try:
        version = AccountStateVersionRepository(conn).bump(account_id)
        jobs_repo.insert(
            job_id,
            account_id,
            requested_by_user_id,
            workflow_name,
            mode,
            "QUEUED",
            input_hash,
            idempotency_key,
            now,
            version,
            parent_job_id=parent_job_id,
        )
        ciphertext = encryptor.encrypt(typed_input_bytes)  # may raise -- rolls back, no partial job
        JobInputsRepository(conn).insert(
            job_id, input_hash, ciphertext, pii_class, now, default_expiry(now_dt, ttl_days)
        )
        EventOutboxRepository(conn).insert(
            account_id, version, "job", "JOB_CREATED", json.dumps({"job_id": job_id, "status": "QUEUED"}), now
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return job_id


def enqueue_dry_run(
    conn,
    *,
    account_id: str,
    requested_by_user_id: str,
    workflow_name: str,
    input_hash: str,
    typed_input_bytes: bytes,
    idempotency_key: str,
    encryptor: InputEncryptor,
) -> str:
    return _enqueue(
        conn,
        account_id=account_id,
        requested_by_user_id=requested_by_user_id,
        workflow_name=workflow_name,
        mode="DRY_RUN",
        input_hash=input_hash,
        typed_input_bytes=typed_input_bytes,
        idempotency_key=idempotency_key,
        encryptor=encryptor,
    )


def enqueue_execute(
    conn,
    *,
    account_id: str,
    requested_by_user_id: str,
    workflow_name: str,
    input_hash: str,
    typed_input_bytes: bytes,
    idempotency_key: str,
    encryptor: InputEncryptor,
    parent_job_id: str,
) -> str:
    """The caller (an API endpoint, INC-17) is responsible for having
    already checked that parent_job_id names a DRY_RUN_VERIFIED job of
    this SAME account_id/workflow_name -- run_execute() re-checks this
    itself regardless (never trusts the caller alone)."""
    return _enqueue(
        conn,
        account_id=account_id,
        requested_by_user_id=requested_by_user_id,
        workflow_name=workflow_name,
        mode="EXECUTE",
        input_hash=input_hash,
        typed_input_bytes=typed_input_bytes,
        idempotency_key=idempotency_key,
        encryptor=encryptor,
        parent_job_id=parent_job_id,
    )


# --------------------------------------------------------------------- #
# Atomic transition (job row + outbox event, one transaction)
# --------------------------------------------------------------------- #


def transition(
    conn,
    job_id: str,
    new_status: str,
    *,
    reason_code: Optional[str] = None,
    plan_hash: Optional[str] = None,
    plan_snapshot: Optional[str] = None,
    authorized_by_user_id: Optional[str] = None,
    started_at: Optional[str] = None,
    finished_at: Optional[str] = None,
) -> None:
    jobs_repo = AutomationJobsRepository(conn)
    row = jobs_repo.get(job_id)
    if row is None:
        raise ValueError("no such job_id")
    account_id = row["account_id"]
    conn.execute("BEGIN IMMEDIATE")
    try:
        version = AccountStateVersionRepository(conn).bump(account_id)
        jobs_repo.update_status(
            job_id,
            new_status,
            version,
            reason_code=reason_code,
            plan_hash=plan_hash,
            plan_snapshot=plan_snapshot,
            authorized_by_user_id=authorized_by_user_id,
            started_at=started_at,
            finished_at=finished_at,
        )
        EventOutboxRepository(conn).insert(
            account_id,
            version,
            "job",
            "JOB_STATUS_CHANGED",
            json.dumps({"job_id": job_id, "status": new_status}),
            _utcnow_iso(),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


# --------------------------------------------------------------------- #
# DRY_RUN (ReadCapability only -- no VerifiedMissionWriter ever exists on
# this path)
# --------------------------------------------------------------------- #


def run_dry_run_planning(conn, job_id: str, *, build_plan: Callable[[], Any]):
    """QUEUED -> PLANNING -> {NEEDS_REVIEW | PLANNED}. `build_plan` is a
    pure callable (no I/O) returning an mcma.planning.plan.ProposedPlan-
    shaped object (duck-typed: .needs_review, .provenance.plan_hash,
    .canonical_json())."""
    transition(conn, job_id, "PLANNING")
    plan = build_plan()
    if plan.needs_review:
        transition(conn, job_id, "NEEDS_REVIEW", plan_hash=plan.provenance.plan_hash, plan_snapshot=plan.canonical_json())
    else:
        transition(conn, job_id, "PLANNED", plan_hash=plan.provenance.plan_hash, plan_snapshot=plan.canonical_json())
    return plan


def run_dry_run_identity_check(conn, job_id: str, *, check_identity_read_only: Callable[[], bool]) -> bool:
    """PLANNED -> READ_ONLY_IDENTITY_CHECK -> {DRY_RUN_VERIFIED |
    IDENTITY_FAILED}. `check_identity_read_only` must use ONLY a
    ReadCapability-shaped object -- this function never constructs, and
    never accepts, anything writer-shaped; it is a bare bool-returning
    callable, structurally incapable of writing."""
    transition(conn, job_id, "READ_ONLY_IDENTITY_CHECK")
    matched = check_identity_read_only()
    if matched:
        transition(conn, job_id, "DRY_RUN_VERIFIED")
    else:
        transition(conn, job_id, "IDENTITY_FAILED")
    return matched


# --------------------------------------------------------------------- #
# EXECUTE (VerifiedMissionWriter; lease held only ACQUIRING_ACCOUNT_LOCK
# through VERIFYING)
# --------------------------------------------------------------------- #


def _require_authorized_parent(conn, job_row) -> dict:
    jobs_repo = AutomationJobsRepository(conn)
    parent_id = job_row["parent_job_id"]
    if not parent_id:
        raise JobAuthorizationError("MISSING_PARENT_DRY_RUN")
    parent = jobs_repo.get(parent_id)
    if parent is None:
        raise JobAuthorizationError("MISSING_PARENT_DRY_RUN")
    if parent["status"] != "DRY_RUN_VERIFIED":
        raise JobAuthorizationError("PARENT_NOT_DRY_RUN_VERIFIED")
    if parent["account_id"] != job_row["account_id"] or parent["workflow_name"] != job_row["workflow_name"]:
        raise JobAuthorizationError("PARENT_ACCOUNT_OR_WORKFLOW_MISMATCH")
    return dict(parent)


def run_execute_planning(
    conn,
    job_id: str,
    *,
    rebuild_plan_from_retained_input: Callable[[], Any],
):
    """Re-derives ExecutablePlanData from the job's OWN retained input
    (never trusts a caller-supplied plan) and re-checks plan_hash/
    input_hash against the approved DRY_RUN parent. Any mismatch fails
    closed to ERROR/INPUT_CHANGED before ever acquiring the account lock."""
    jobs_repo = AutomationJobsRepository(conn)
    job_row = jobs_repo.get(job_id)
    parent = _require_authorized_parent(conn, job_row)

    transition(conn, job_id, "PLANNING")
    plan = rebuild_plan_from_retained_input()

    if job_row["input_hash"] != parent["input_hash"] or plan.provenance.plan_hash != parent["plan_hash"]:
        transition(conn, job_id, "ERROR", reason_code="INPUT_CHANGED")
        raise JobAuthorizationError("INPUT_CHANGED")

    if plan.needs_review:
        transition(conn, job_id, "NEEDS_REVIEW", plan_hash=plan.provenance.plan_hash, plan_snapshot=plan.canonical_json())
    else:
        transition(conn, job_id, "PLANNED", plan_hash=plan.provenance.plan_hash, plan_snapshot=plan.canonical_json())
    return plan


def run_execute_write(
    conn,
    job_id: str,
    *,
    acquire_lease_and_verify_identity: Callable[[], Any],
    perform_writes_and_verify: Callable[[Any], bool],
) -> str:
    """PLANNED -> ACQUIRING_ACCOUNT_LOCK -> IDENTITY_VERIFYING ->
    {IDENTITY_VERIFIED | IDENTITY_FAILED} -> WRITING -> {VERIFYING ->
    READY_FOR_HUMAN_REVIEW | WRITE_ABORTED}. Returns the final status.
    `acquire_lease_and_verify_identity` raises on identity mismatch/lease
    failure; `perform_writes_and_verify` returns True only when every row
    write, read-back, and the native financial verification all
    succeeded -- False (or a raised exception) means WRITE_ABORTED."""
    transition(conn, job_id, "ACQUIRING_ACCOUNT_LOCK")
    transition(conn, job_id, "IDENTITY_VERIFYING")
    try:
        writer = acquire_lease_and_verify_identity()
    except Exception:
        transition(conn, job_id, "IDENTITY_FAILED")
        return "IDENTITY_FAILED"
    transition(conn, job_id, "IDENTITY_VERIFIED")

    transition(conn, job_id, "WRITING")
    try:
        succeeded = perform_writes_and_verify(writer)
    except Exception:
        succeeded = False
    if not succeeded:
        transition(conn, job_id, "WRITE_ABORTED")
        return "WRITE_ABORTED"

    transition(conn, job_id, "VERIFYING")
    transition(conn, job_id, "READY_FOR_HUMAN_REVIEW", finished_at=_utcnow_iso())
    return "READY_FOR_HUMAN_REVIEW"
