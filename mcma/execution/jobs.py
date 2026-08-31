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

from mcma.domain.portal_accounts import PortalAccountProfile
from mcma.execution.inputs import InputEncryptor, default_expiry
from mcma.persistence.repositories.accounts import AccountsRepository
from mcma.persistence.repositories.audit import AuditEventsRepository
from mcma.persistence.repositories.jobs import AutomationJobsRepository, JobInputsRepository
from mcma.persistence.repositories.outbox import AccountStateVersionRepository, EventOutboxRepository
from mcma.persistence.leases import release_lease_if_owned_by_job

# Correction batch (owner amendment, human browser handoff): READY_FOR_
# HUMAN_REVIEW is NO LONGER terminal -- it means agent work is finished
# and the browser stays open for human review, not that the job is done.
# AWAITING_HUMAN_CONFIRMATION IS treated as terminal here (excluded from
# restart reconciliation's list_non_terminal(), per F.7 "may remain
# awaiting explicit human confirmation after restart") even though it is
# not semantically final -- only an explicit employee action
# (confirm_review_completed/report_review_problem) ever moves it further;
# nothing in this module auto-advances it. HUMAN_CONFIRMED_COMPLETE is
# genuinely terminal.
TERMINAL_STATUSES = frozenset(
    {
        "DRY_RUN_VERIFIED",
        "NEEDS_REVIEW",
        "IDENTITY_FAILED",
        "WRITE_ABORTED",
        "AWAITING_HUMAN_CONFIRMATION",
        "HUMAN_CONFIRMED_COMPLETE",
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
    authorized_by_user_id: Optional[str] = None,
) -> str:
    # MAMDA read-only enforcement, defense-in-depth layer 2 (correction
    # batch). Fable-review-2 correction: this now runs BEFORE the
    # idempotency short-circuit below -- previously a MAMDA account with
    # any pre-existing job under this idempotency_key (e.g. from before
    # this enforcement shipped, or inserted by a lower-level path) would
    # bypass this check entirely on resubmit. It is re-checked here
    # regardless of the API (layer 1) already having checked it.
    _require_mcma_writable_account(conn, account_id)

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
            authorized_by_user_id=authorized_by_user_id,
        )
        ciphertext = encryptor.encrypt(typed_input_bytes)  # may raise -- rolls back, no partial job
        JobInputsRepository(conn).insert(
            job_id, input_hash, ciphertext, pii_class, now, default_expiry(now_dt, ttl_days)
        )
        EventOutboxRepository(conn).insert(
            account_id, version, "job", "JOB_CREATED", json.dumps({"job_id": job_id, "status": "QUEUED"}), now
        )
        # Employee account selection (correction batch, section E): the
        # selected account_id is recorded in BOTH the job row (above) and
        # here, in audit data, atomically with creation.
        AuditEventsRepository(conn).record(
            uuid.uuid4().hex, "JOB_CREATED", now, actor_user_id=requested_by_user_id, account_id=account_id, job_id=job_id
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
    authorized_by_user_id: Optional[str] = None,
) -> str:
    """The caller (an API endpoint, INC-17) is responsible for having
    already checked that parent_job_id names a DRY_RUN_VERIFIED job of
    this SAME account_id/workflow_name -- run_execute() re-checks this
    itself regardless (never trusts the caller alone). `authorized_by_
    user_id` is normally known at EXECUTE-creation time (the caller of
    POST /executions) -- passing it here records it atomically with
    creation, avoiding a separate non-atomic post-hoc update (Fable-
    review-2 correction)."""
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
        authorized_by_user_id=authorized_by_user_id,
    )


# --------------------------------------------------------------------- #
# Atomic transition (job row + outbox event, one transaction)
# --------------------------------------------------------------------- #


class JobPreconditionMismatch(JobAuthorizationError):
    """Raised by transition() when `expected_from_statuses` is given and
    the job's FRESHLY re-read status (inside the transaction) is no
    longer one of them -- carries the observed status so the caller can
    decide how to report it. `reason_code` is fixed
    (PRECONDITION_STATUS_MISMATCH); use `.observed_status` for detail."""

    def __init__(self, observed_status: str) -> None:
        super().__init__("PRECONDITION_STATUS_MISMATCH")
        self.observed_status = observed_status


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
    audit_actor_user_id: Optional[str] = None,
    audit_action: Optional[str] = None,
    expected_from_statuses: Optional[frozenset] = None,
) -> None:
    """`audit_actor_user_id`/`audit_action` are optional (correction batch,
    human browser handoff, section G): when `audit_action` is given, an
    audit_events row is written in the SAME transaction as the job-row
    update and outbox event -- G requires the human-confirmation
    transition to be atomic with its audit record, not a second,
    separately-committed write.

    `expected_from_statuses`, when given, closes a TOCTOU race (Fable-
    review-2 correction): the job's status is re-read INSIDE the
    BEGIN IMMEDIATE transaction (which serializes against any other
    writer via SQLite's own locking) and compared against this set
    immediately before writing -- not just once, earlier, outside any
    transaction. Two concurrent callers racing the SAME job (e.g.
    confirm_review_completed and report_review_problem both firing from
    a double-click or two different employees) can no longer both
    observe the same stale status and both successfully commit a
    transition; the second to acquire the lock sees the FIRST one's
    already-applied change and raises JobPreconditionMismatch instead of
    silently overwriting it."""
    jobs_repo = AutomationJobsRepository(conn)
    row = jobs_repo.get(job_id)
    if row is None:
        raise ValueError("no such job_id")
    account_id = row["account_id"]
    conn.execute("BEGIN IMMEDIATE")
    try:
        if expected_from_statuses is not None:
            fresh_status = jobs_repo.get(job_id)["status"]
            if fresh_status not in expected_from_statuses:
                # Let the single except-block below perform the ONE
                # rollback -- calling ROLLBACK twice on this connection
                # would itself raise (no active transaction), masking
                # this precondition failure.
                raise JobPreconditionMismatch(fresh_status)
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
        if audit_action is not None:
            AuditEventsRepository(conn).record(
                uuid.uuid4().hex,
                audit_action,
                _utcnow_iso(),
                actor_user_id=audit_actor_user_id,
                account_id=account_id,
                job_id=job_id,
            )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


# --------------------------------------------------------------------- #
# DRY_RUN (ReadCapability only -- no VerifiedMissionWriter ever exists on
# this path)
# --------------------------------------------------------------------- #


def _require_mcma_writable_account(conn, account_id: str) -> None:
    """MAMDA read-only enforcement, defense-in-depth layer 2 (correction
    batch / owner amendment). ALWAYS re-reads the account row fresh --
    never trusts that the API (layer 1) already checked this, and this
    check alone is still not the last word: mcma.portal.writer's
    require_mcma_writer_account() (layer 3) independently refuses to
    construct a writer for anything but an McmaWriterAccountContext, so a
    caller that skipped this function cannot reach a writer either way."""
    account = AccountsRepository(conn).get(account_id)
    if account is None:
        raise JobAuthorizationError("ACCOUNT_NOT_FOUND")
    if not account.active:
        raise JobAuthorizationError("ACCOUNT_NOT_ACTIVE")
    profile = PortalAccountProfile.from_row(account.entity, account.scope)
    if not profile.is_mcma:
        raise JobAuthorizationError("MAMDA_ACCOUNT_NOT_WRITABLE")


def _require_mode(job_row, expected_mode: str) -> None:
    """Fable-review correction: without this check, run_dry_run_planning/
    run_dry_run_identity_check could drive an EXECUTE-mode job into
    DRY_RUN_VERIFIED, which _require_authorized_parent would then accept
    as a valid parent for a THIRD job -- closing that gap requires
    checking mode at both ends (here, and in _require_authorized_parent
    below)."""
    if job_row["mode"] != expected_mode:
        raise JobAuthorizationError(f"WRONG_JOB_MODE_EXPECTED_{expected_mode}")


def run_dry_run_planning(conn, job_id: str, *, build_plan: Callable[[], Any]):
    """QUEUED -> PLANNING -> {NEEDS_REVIEW | PLANNED}. `build_plan` is a
    pure callable (no I/O) returning an mcma.planning.plan.ProposedPlan-
    shaped object (duck-typed: .needs_review, .provenance.plan_hash,
    .canonical_json())."""
    _require_mode(AutomationJobsRepository(conn).get(job_id), "DRY_RUN")
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
    _require_mode(AutomationJobsRepository(conn).get(job_id), "DRY_RUN")
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
    if parent["mode"] != "DRY_RUN":
        raise JobAuthorizationError("PARENT_NOT_DRY_RUN_VERIFIED")
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
    _require_mode(job_row, "EXECUTE")
    _require_mcma_writable_account(conn, job_row["account_id"])
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
    succeeded -- False (or a raised exception) means WRITE_ABORTED.

    Fable-review correction: this function used to trust its caller to
    have already run run_execute_planning (which performs the parent-
    authorization and input_hash/plan_hash re-check) -- calling this
    directly on a job that skipped planning bypassed that check entirely.
    It now re-verifies both the job's own state (mode EXECUTE, status
    PLANNED) and its parent authorization itself, so the guarantee holds
    regardless of what the caller did or didn't call first."""
    job_row = AutomationJobsRepository(conn).get(job_id)
    _require_mode(job_row, "EXECUTE")
    if job_row["status"] != "PLANNED":
        raise JobAuthorizationError("EXECUTE_WRITE_REQUIRES_PLANNED_STATUS")
    _require_mcma_writable_account(conn, job_row["account_id"])
    _require_authorized_parent(conn, job_row)

    transition(conn, job_id, "ACQUIRING_ACCOUNT_LOCK")
    transition(conn, job_id, "IDENTITY_VERIFYING")
    try:
        writer = acquire_lease_and_verify_identity()
    except Exception:
        transition(conn, job_id, "IDENTITY_FAILED")
        return "IDENTITY_FAILED"
    transition(conn, job_id, "IDENTITY_VERIFIED")

    transition(conn, job_id, "WRITING")
    write_exception_reason = None
    try:
        succeeded = perform_writes_and_verify(writer)
    except Exception as exc:
        succeeded = False
        # A diagnostic-only reason code: an exception mid-write (rows
        # possibly already partially applied) is still WRITE_ABORTED per
        # WORKFLOW_STATE_MODEL.md §4 (a live run's own write-time failure
        # is a normal-runtime outcome, distinct from INTERRUPTED_NEEDS_
        # HUMAN_REVIEW, which is reserved for crash/restart reconciliation
        # only) -- this only records WHY, it never changes the status.
        write_exception_reason = f"WRITE_EXCEPTION_{type(exc).__name__}"
    if not succeeded:
        transition(conn, job_id, "WRITE_ABORTED", reason_code=write_exception_reason)
        return "WRITE_ABORTED"

    transition(conn, job_id, "VERIFYING")
    # F.8 (correction batch): finished_at is NOT set here -- READY_FOR_
    # HUMAN_REVIEW is no longer a terminal outcome (the browser stays
    # open for human review); finished_at is set only at a genuine
    # terminal outcome (HUMAN_CONFIRMED_COMPLETE, WRITE_ABORTED,
    # IDENTITY_FAILED, INTERRUPTED_NEEDS_HUMAN_REVIEW, ABORTED_ON_RESTART).
    transition(conn, job_id, "READY_FOR_HUMAN_REVIEW")
    return "READY_FOR_HUMAN_REVIEW"


async def run_execute_write_async(
    conn,
    job_id: str,
    *,
    acquire_lease_and_verify_identity: Callable[[], Any],
    perform_writes_and_verify: Callable[[Any], bool],
) -> str:
    """Async twin of run_execute_write (pilot-runner correction), for the
    real job runner (mcma.execution.runner) where the injected steps are
    genuine awaitable Playwright/portal calls. run_execute_write's own
    synchronous callables cannot be bridged onto the runner's asyncio
    event loop from here -- Playwright's async API is tied to the loop it
    was started on, so a callable that internally spawned its own loop/
    thread to "go synchronous" would silently break it. This mirrors
    run_execute_write's exact transition sequence and exception handling
    with `await` in place of a plain call, so real browser I/O happens
    only AFTER the corresponding transition() has already committed --
    e.g. the lease is acquired/browser opened only once IDENTITY_
    VERIFYING is durably recorded, and rows are only written once WRITING
    is durably recorded -- instead of the reverse (all I/O first, state
    caught up afterward), which left a crash mid-I/O invisible to restart
    reconciliation. Any change to the status sequence must be made in
    BOTH this function and run_execute_write.
    """
    job_row = AutomationJobsRepository(conn).get(job_id)
    _require_mode(job_row, "EXECUTE")
    if job_row["status"] != "PLANNED":
        raise JobAuthorizationError("EXECUTE_WRITE_REQUIRES_PLANNED_STATUS")
    _require_mcma_writable_account(conn, job_row["account_id"])
    _require_authorized_parent(conn, job_row)

    transition(conn, job_id, "ACQUIRING_ACCOUNT_LOCK")
    transition(conn, job_id, "IDENTITY_VERIFYING")
    try:
        writer = await acquire_lease_and_verify_identity()
    except Exception:
        transition(conn, job_id, "IDENTITY_FAILED")
        return "IDENTITY_FAILED"
    transition(conn, job_id, "IDENTITY_VERIFIED")

    transition(conn, job_id, "WRITING")
    write_exception_reason = None
    try:
        succeeded = await perform_writes_and_verify(writer)
    except Exception as exc:
        succeeded = False
        write_exception_reason = f"WRITE_EXCEPTION_{type(exc).__name__}"
    if not succeeded:
        transition(conn, job_id, "WRITE_ABORTED", reason_code=write_exception_reason)
        return "WRITE_ABORTED"

    transition(conn, job_id, "VERIFYING")
    transition(conn, job_id, "READY_FOR_HUMAN_REVIEW")
    return "READY_FOR_HUMAN_REVIEW"


# --------------------------------------------------------------------- #
# Human browser handoff (correction batch / owner amendment,
# WORKFLOW_STATE_MODEL.md correction): READY_FOR_HUMAN_REVIEW means agent
# work is finished and a visible browser is left open for the employee to
# review, manually click Valider/Clôture, and close it themselves -- this
# module never touches Valider/Clôture or the browser itself.
# `release_lease`, like every portal-facing step in this module, is an
# injected callable (never a direct mcma.portal/lease import) -- the real
# job runner that will eventually own an mcma.persistence.leases.
# AccountLeaseHandle wires it in; tests inject a stub.
# --------------------------------------------------------------------- #

_WRITE_IN_PROGRESS_STATUSES = frozenset(
    {"ACQUIRING_ACCOUNT_LOCK", "IDENTITY_VERIFYING", "IDENTITY_VERIFIED", "WRITING", "VERIFYING"}
)
_HUMAN_HANDOFF_STATUSES = frozenset({"READY_FOR_HUMAN_REVIEW", "AWAITING_HUMAN_CONFIRMATION"})


def transition_on_browser_closed(conn, job_id: str, *, release_lease: Optional[Callable[[], None]] = None) -> str:
    """Driven by the real job runner's page/context close callback (never
    auto-invoked by anything in this module). Browser closure BEFORE
    READY_FOR_HUMAN_REVIEW (write still in progress, or the write phase
    already reached READY but the browser is closing for the first time
    from that exact state is handled by the branch below, not this one)
    fails closed to INTERRUPTED_NEEDS_HUMAN_REVIEW -- never auto-resumed.
    Closure AFTER READY_FOR_HUMAN_REVIEW is expected human behavior and
    moves to AWAITING_HUMAN_CONFIRMATION -- closure ALONE never means
    success (F.4); only confirm_review_completed can mark the job done.
    The lease is released on the INTERRUPTED path (nothing further will
    run) but deliberately NOT on the AWAITING_HUMAN_CONFIRMATION path --
    it stays held until confirm_review_completed/report_review_problem so
    no second job can concurrently use the same shared portal account
    while a human is still mid-review."""
    job_row = AutomationJobsRepository(conn).get(job_id)
    if job_row is None:
        raise ValueError("no such job_id")
    status = job_row["status"]
    if status == "READY_FOR_HUMAN_REVIEW":
        try:
            transition(
                conn, job_id, "AWAITING_HUMAN_CONFIRMATION",
                expected_from_statuses=frozenset({"READY_FOR_HUMAN_REVIEW"}),
            )
        except JobPreconditionMismatch as exc:
            # Fable-review-2 correction: re-checked atomically -- a
            # concurrent caller could have already moved this job (e.g.
            # a restart's reconciliation racing a close callback) between
            # the read above and this transition.
            raise JobAuthorizationError("NO_ACTIVE_BROWSER_SESSION_FOR_JOB") from exc
        return "AWAITING_HUMAN_CONFIRMATION"
    if status in _WRITE_IN_PROGRESS_STATUSES:
        try:
            transition(
                conn, job_id, "INTERRUPTED_NEEDS_HUMAN_REVIEW",
                reason_code="BROWSER_CLOSED_BEFORE_READY", finished_at=_utcnow_iso(),
                expected_from_statuses=_WRITE_IN_PROGRESS_STATUSES,
            )
        except JobPreconditionMismatch as exc:
            raise JobAuthorizationError("NO_ACTIVE_BROWSER_SESSION_FOR_JOB") from exc
        if release_lease is not None:
            release_lease()
        return "INTERRUPTED_NEEDS_HUMAN_REVIEW"
    raise JobAuthorizationError("NO_ACTIVE_BROWSER_SESSION_FOR_JOB")


def confirm_review_completed(
    conn, job_id: str, *, confirmed_by_user_id: str, release_lease: Optional[Callable[[], None]] = None
) -> str:
    """The ONLY way a job can ever reach HUMAN_CONFIRMED_COMPLETE. Records
    ONLY a human attestation (F.5) -- this never claims the application
    independently observed Valider/Clôture. Idempotent: retrying against
    an already-HUMAN_CONFIRMED_COMPLETE job returns that same state rather
    than raising (G's idempotent-retry requirement) -- but every OTHER
    status is rejected, never silently "completed" out of turn."""
    job_row = AutomationJobsRepository(conn).get(job_id)
    if job_row is None:
        raise ValueError("no such job_id")
    if job_row["status"] == "HUMAN_CONFIRMED_COMPLETE":
        return "HUMAN_CONFIRMED_COMPLETE"
    if job_row["status"] != "AWAITING_HUMAN_CONFIRMATION":
        raise JobAuthorizationError("REVIEW_NOT_AWAITING_CONFIRMATION")
    try:
        transition(
            conn,
            job_id,
            "HUMAN_CONFIRMED_COMPLETE",
            finished_at=_utcnow_iso(),
            audit_actor_user_id=confirmed_by_user_id,
            audit_action="HUMAN_CONFIRMED_COMPLETE",
            # Fable-review-2 correction: re-checked atomically inside the
            # transaction -- closes a race against a concurrent
            # report_review_problem (or a second confirm) that could
            # otherwise both read AWAITING_HUMAN_CONFIRMATION and both
            # successfully commit, silently overwriting one outcome.
            expected_from_statuses=frozenset({"AWAITING_HUMAN_CONFIRMATION"}),
        )
    except JobPreconditionMismatch as exc:
        if exc.observed_status == "HUMAN_CONFIRMED_COMPLETE":
            return "HUMAN_CONFIRMED_COMPLETE"  # lost the race to another confirm -- still idempotently done
        raise JobAuthorizationError("REVIEW_NOT_AWAITING_CONFIRMATION") from exc
    if release_lease is not None:
        release_lease()
    else:
        # Restart-safe fallback (pilot-runner correction): no in-memory
        # handle survived to be passed in -- fenced to this job's own
        # account_leases ownership, see release_lease_if_owned_by_job.
        release_lease_if_owned_by_job(conn, job_row["account_id"], job_id)
    return "HUMAN_CONFIRMED_COMPLETE"


def report_review_problem(
    conn,
    job_id: str,
    *,
    reported_by_user_id: str,
    reason_code: str,
    release_lease: Optional[Callable[[], None]] = None,
) -> str:
    """The "Problem / not completed" action: a documented human-review/
    error outcome (INTERRUPTED_NEEDS_HUMAN_REVIEW, the same status restart
    reconciliation already uses for an unresolved write) rather than
    falsely marking the job HUMAN_CONFIRMED_COMPLETE. Valid from either
    human-handoff status -- the employee may report a problem before OR
    after closing the browser."""
    job_row = AutomationJobsRepository(conn).get(job_id)
    if job_row is None:
        raise ValueError("no such job_id")
    if job_row["status"] not in _HUMAN_HANDOFF_STATUSES:
        raise JobAuthorizationError("NOT_IN_HUMAN_HANDOFF")
    try:
        transition(
            conn,
            job_id,
            "INTERRUPTED_NEEDS_HUMAN_REVIEW",
            reason_code=reason_code,
            finished_at=_utcnow_iso(),
            audit_actor_user_id=reported_by_user_id,
            audit_action="HUMAN_REPORTED_PROBLEM",
            # Fable-review-2 correction: re-checked atomically -- closes
            # the same race class as confirm_review_completed's.
            expected_from_statuses=_HUMAN_HANDOFF_STATUSES,
        )
    except JobPreconditionMismatch as exc:
        raise JobAuthorizationError("NOT_IN_HUMAN_HANDOFF") from exc
    if release_lease is not None:
        release_lease()
    else:
        # Restart-safe fallback (pilot-runner correction): see
        # confirm_review_completed's identical fallback above.
        release_lease_if_owned_by_job(conn, job_row["account_id"], job_id)
    return "INTERRUPTED_NEEDS_HUMAN_REVIEW"
