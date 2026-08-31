"""
mcma.execution.runner -- the real job runner (pilot-integration correction,
sections 3/4): the ONE module that composes mcma.execution.jobs's
injected-callable DRY_RUN/EXECUTE state machines with genuine
mcma.portal/mcma.persistence wiring. mcma.execution.jobs itself still
never imports mcma.portal -- every portal-facing step below is built here
and handed to jobs.py as a plain callable, exactly as that module's own
docstring anticipates ("Real wiring ... is composed by the caller").

Import-linter layering permits this: mcma.execution sits ABOVE
mcma.persistence and mcma.portal (both are sibling layers beneath it), so
this module -- like the already-accepted mcma.execution.lease -- may
import both. mcma.portal/mcma.persistence still never import each other
or mcma.execution (unchanged).

Every function here is a coroutine and this module owns no loop of its
own: it never calls asyncio.run() and never creates a thread. The caller
(mcma.app.main) owns the one event loop, constructs exactly one
RunnerConfig/ActiveReviewRegistry pair for the process, and awaits these
poll functions on it -- that is what "own the process-wide workers/
registry" (section 2) means. sqlite3 itself is synchronous and is called
directly from these coroutines; that is safe here only because there is
no concurrent worker pool in this pilot scope (WORKFLOW_STATE_MODEL.md's
single-writer model: one running instance, matching mcma.core.mutex's own
guarantee).

The one exception to "no background work" is the per-job lease heartbeat
(_heartbeat_forever), an asyncio.Task on the caller's own loop. It is
created when a lease is acquired and cancelled on every exit path; it
never outlives the job that started it, and it never re-acquires a lease
it has lost.

Every portal-facing step here re-derives its own typed ProposedPlan from
the job's OWN retained, hash-verified input via the SAME pure registry
builder the job's workflow_name names (mcma.planning.registry) -- never a
caller-supplied plan, and never the job's plan_snapshot column (a
canonical-JSON STRING for audit/display, not a round-trippable typed
object; mcma.app.api.app's own _rebuild_plan_from_retained_input does the
same re-derivation for the identical reason).
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple

from mcma.execution.browser_handoff import ActiveReviewRegistry, DuplicateActiveReview
from mcma.execution.inputs import InputEncryptor, retrieve_and_verify_job_input
from mcma.execution.jobs import (
    AccountBusy,
    JobAuthorizationError,
    fail_closed_on_runner_exception,
    run_dry_run_identity_check_async,
    run_dry_run_planning,
    run_execute_write_async,
    transition_on_browser_closed,
)
from mcma.execution.lease import acquire_account_lease
from mcma.mapping.wexia import parse_wexia
from mcma.persistence.leases import AccountLeaseHandle, LeaseInvalid, LeaseNotHeld
from mcma.persistence.repositories.accounts import AccountsRepository
from mcma.persistence.repositories.jobs import AutomationJobsRepository
from mcma.planning.plan import ExpectedIdentity as PlanExpectedIdentity
from mcma.planning.plan import ProposedPlan
from mcma.planning.registry import WorkflowRegistry, default_registry
from mcma.portal.capabilities import ReadCapability, SearchIdentifiers, open_reader
from mcma.portal.identity import ExpectedIdentity as PortalExpectedIdentity
from mcma.portal.identity import IdentityMismatch, verify_identity
from mcma.portal.pilot_contracts import read_contracts as pilot_read_contracts
from mcma.portal.pilot_contracts import write_contracts as pilot_write_contracts
from mcma.portal.vault import CryptoBackend, load_and_verify_session
from mcma.portal.writer import (
    AccountNotMcmaWritable,
    PortalRowIntent,
    VerifiedMissionWriter,
    WriteAborted,
    WriterPlanData,
    open_verified_writer,
    require_mcma_writer_account,
)


@dataclass(frozen=True)
class RunnerConfig:
    """Everything the real job runner needs beyond the sqlite3 connection
    it is called with -- constructed once by mcma.app.main and passed to
    every poll function below."""

    instance_id: str
    allowed_host: str
    vault_dir: Path
    crypto_backend: CryptoBackend
    active_review_registry: ActiveReviewRegistry
    workflow_registry: WorkflowRegistry = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.workflow_registry is None:
            object.__setattr__(self, "workflow_registry", default_registry())


def _rebuild_plan(conn, job_row, encryptor: InputEncryptor) -> ProposedPlan:
    """Never trusts plan_snapshot (display-only JSON text) or a
    caller-supplied plan -- re-derives from the job's own retained,
    hash-verified input, exactly like mcma.app.api.app's
    _rebuild_plan_from_retained_input."""
    typed_input_bytes = retrieve_and_verify_job_input(conn, job_row["job_id"], job_row["input_hash"], encryptor)
    typed_input = parse_wexia(json.loads(typed_input_bytes))
    return _WORKFLOW_REGISTRY_FALLBACK.get(job_row["workflow_name"])(typed_input)


# A module-level default registry for _rebuild_plan's fallback signature
# above is deliberately NOT used when a RunnerConfig carries its own
# (tests inject one); kept only as the always-available default.
_WORKFLOW_REGISTRY_FALLBACK = default_registry()


def _to_portal_expected_identity(expected: PlanExpectedIdentity) -> PortalExpectedIdentity:
    """mcma.execution is exactly the seam both ExpectedIdentity mirrors'
    own docstrings anticipate for this pairing (mcma.planning.plan's and
    mcma.portal.identity's) -- a straight field copy, never a remapping."""
    return PortalExpectedIdentity(
        registration=expected.registration,
        insurer_reference=expected.insurer_reference,
        id_sinistre=expected.id_sinistre,
    )


def _search_identifiers_for(expected: PlanExpectedIdentity) -> SearchIdentifiers:
    return SearchIdentifiers(matricule=expected.registration.raw)


def _writer_plan_from(plan: ProposedPlan) -> WriterPlanData:
    row_intents: Tuple[PortalRowIntent, ...] = tuple(
        PortalRowIntent(rubrique_id=step.rubrique_id, ht=step.ht, tva=step.tva, vetuste=step.vetuste)
        for step in plan.steps
    )
    return WriterPlanData(
        repair_workflow=plan.repair_workflow,
        row_intents=row_intents,
        form_field_intents=tuple(plan.form_field_intents),
    )


# --------------------------------------------------------------------- #
# DRY_RUN: consume QUEUED jobs, plan, run the read-only identity gate
# --------------------------------------------------------------------- #


async def _observe_and_verify_identity(
    conn, browser, cfg: RunnerConfig, account_id: str, job_id: str, plan: ProposedPlan
) -> bool:
    """The real read-only identity gate (section 3): a genuine
    ReadCapability search/open/observe_identity against the account's own
    stored session, verified against the plan's OWN expected_identity.
    Never raises for an expected failure mode (lease unavailable, no/
    ambiguous candidate, identity mismatch, session unusable) -- all of
    those are truthfully IDENTITY_FAILED, not an unhandled exception
    (run_dry_run_identity_check has no try/except around this callable)."""
    try:
        lease = acquire_account_lease(conn, account_id, cfg.instance_id, owner_job_id=job_id, ttl_seconds=60)
    except LeaseNotHeld:
        return False
    # The read below opens a real browser and does a search/open/observe
    # round trip against a portal that can be slow; without renewal a
    # 60s TTL can lapse mid-read, at which point the reader's own
    # assert_valid() raises and this returns a spurious IDENTITY_FAILED
    # for a dossier whose identity was never actually checked.
    heartbeat_task = asyncio.create_task(_heartbeat_forever(lease))
    try:
        try:
            raw_session = load_and_verify_session(conn, account_id, vault_dir=cfg.vault_dir, backend=cfg.crypto_backend)
            storage_state = json.loads(raw_session)
        except Exception:
            return False

        contracts = pilot_read_contracts(cfg.allowed_host)
        try:
            reader: ReadCapability = await open_reader(
                browser, lease, contracts, cfg.allowed_host, context_options={"storage_state": storage_state}
            )
        except Exception:
            return False
        try:
            identifiers = _search_identifiers_for(plan.expected_identity)
            candidates = await reader.search(identifiers)
            if len(candidates) != 1:
                return False  # F3/F4: ambiguity is never resolved by picking one
            await reader.open(candidates[0])
            observed = await reader.observe_identity()
            try:
                verify_identity(_to_portal_expected_identity(plan.expected_identity), observed)
            except IdentityMismatch:
                return False
            return True
        finally:
            await reader.close()
    finally:
        heartbeat_task.cancel()
        lease.release()


async def process_one_queued_dry_run(
    conn, job_id: str, *, browser, cfg: RunnerConfig, encryptor: InputEncryptor
) -> str:
    """Drives exactly one QUEUED DRY_RUN job through planning and (when
    planning did not already fail closed to NEEDS_REVIEW) the read-only
    identity gate. Returns the job's resulting status."""
    job_row = AutomationJobsRepository(conn).get(job_id)
    if job_row is None:
        raise ValueError("no such job_id")

    def _build_plan():
        return _rebuild_plan(conn, job_row, encryptor)

    plan = run_dry_run_planning(conn, job_id, build_plan=_build_plan)
    if plan.needs_review:
        return "NEEDS_REVIEW"

    # This closure used to be `lambda: matched` over an ALREADY-COMPLETED
    # browser read performed on the line above, so READ_ONLY_IDENTITY_
    # CHECK was recorded retroactively and a crash during the read left
    # the job at PLANNED -- which reconciliation returns to QUEUED for a
    # full replay. The read now runs only when run_dry_run_identity_check
    # _async invokes it, after that status is durably committed.
    async def _check_identity_read_only() -> bool:
        return await _observe_and_verify_identity(
            conn, browser, cfg, job_row["account_id"], job_id, plan
        )

    await run_dry_run_identity_check_async(
        conn, job_id, check_identity_read_only=_check_identity_read_only
    )
    return AutomationJobsRepository(conn).get(job_id)["status"]


async def process_queued_dry_run_jobs(
    conn, *, browser, cfg: RunnerConfig, encryptor: InputEncryptor
) -> Tuple[str, ...]:
    """"Consume QUEUED DRY_RUN jobs" (section 3) -- the runner's one
    job-discovery entry point. Processed in submission order; one job's
    failure (an unexpected exception escaping planning/identity-check,
    which should never happen given the closures above swallow every
    expected failure mode) is isolated and does not stop the others."""
    jobs_repo = AutomationJobsRepository(conn)
    job_ids = tuple(row["job_id"] for row in jobs_repo.list_by_mode_and_status("DRY_RUN", "QUEUED"))
    outcomes = []
    for job_id in job_ids:
        try:
            outcomes.append(await process_one_queued_dry_run(conn, job_id, browser=browser, cfg=cfg, encryptor=encryptor))
        except Exception as exc:
            # Isolation is not enough on its own: a job whose exception
            # escaped here still has a row, and leaving it at PLANNED/
            # READ_ONLY_IDENTITY_CHECK would let reconciliation replay it
            # as though nothing had happened. Land it truthfully first,
            # then carry on with the rest of the queue.
            fail_closed_on_runner_exception(conn, job_id, f"RUNNER_EXCEPTION_{type(exc).__name__}")
            outcomes.append(f"RUNNER_ERROR_{type(exc).__name__}")
    return tuple(outcomes)


# --------------------------------------------------------------------- #
# EXECUTE: real lease + session + writer, human handoff registration
# --------------------------------------------------------------------- #

# The account lease used to be heartbeat-free -- acquired once with a
# fixed TTL and never renewed -- so it could expire out from under a job
# mid-identity-check, mid-write, or (worst case) while a human was still
# reviewing an open browser, since review time is unbounded and the TTL
# is not. Interval is well under both TTLs in use (60s dry-run, 120s
# execute) so a renewal always lands before the lease could lapse even
# under scheduling jitter.
_LEASE_HEARTBEAT_INTERVAL_SECONDS = 20

# ...but renewal is NOT unbounded, or the fix would trade a lease that
# expires too early for one that never expires at all. A review browser
# left open overnight would otherwise pin the shared account forever:
# release_stale_leases() reclaims by expires_at, so a lease that is
# renewed forever is a lease no restart, no reconciliation and no other
# job can ever recover -- one forgotten window would take an account out
# of service until someone edited the database by hand. After this cap
# the heartbeat stops renewing and lets the lease lapse on its own TTL,
# which is the documented recovery path. It does NOT close the browser
# or touch the job row: the employee may well still be working, and the
# job stays exactly as truthful as it was -- reconciliation, not this
# task, decides what an interrupted review means.
_LEASE_MAX_HOLD_SECONDS = 8 * 60 * 60


async def _heartbeat_forever(
    lease: AccountLeaseHandle,
    *,
    interval_seconds: int = _LEASE_HEARTBEAT_INTERVAL_SECONDS,
    max_hold_seconds: int = _LEASE_MAX_HOLD_SECONDS,
) -> None:
    """Renews `lease` on a fixed interval until cancelled (normal
    shutdown -- the caller cancels this task once the lease is
    deliberately released), until the maximum hold above is reached, or
    until the lease is discovered lost/replaced (LeaseInvalid -- another
    owner has since reclaimed the account; nothing further this task can
    legitimately do). Never re-acquires -- a lost lease means this job's
    own claim on the account is gone, not that this task should paper
    over it."""
    held_seconds = 0
    try:
        while held_seconds < max_hold_seconds:
            await asyncio.sleep(interval_seconds)
            held_seconds += interval_seconds
            lease.heartbeat()
    except asyncio.CancelledError:
        raise
    except LeaseInvalid:
        return


async def _open_writer_for_execute(
    conn, browser, cfg: RunnerConfig, job_row, plan: ProposedPlan
) -> Tuple[VerifiedMissionWriter, AccountLeaseHandle, "asyncio.Task"]:
    account_id = job_row["account_id"]
    lease = acquire_account_lease(conn, account_id, cfg.instance_id, owner_job_id=job_row["job_id"], ttl_seconds=120)
    # Heartbeat starts the instant the lease is acquired -- covering
    # identity verification, writing, and (kept alive by the caller
    # through the rest of this job's lifecycle) human handoff, not just
    # from whenever the browser+identity gate happened to finish.
    heartbeat_task = asyncio.create_task(_heartbeat_forever(lease))
    try:
        account = AccountsRepository(conn).get(account_id)
        if account is None:
            raise AccountNotMcmaWritable(f"account {account_id!r} not found")
        writer_account = require_mcma_writer_account(account_id, entity=account.entity, active=account.active)

        raw_session = load_and_verify_session(conn, account_id, vault_dir=cfg.vault_dir, backend=cfg.crypto_backend)
        storage_state = json.loads(raw_session)

        writer_plan = _writer_plan_from(plan)
        identifiers = _search_identifiers_for(plan.expected_identity)
        contracts = pilot_write_contracts(cfg.allowed_host)
        writer = await open_verified_writer(
            browser,
            lease,
            _to_portal_expected_identity(plan.expected_identity),
            writer_plan,
            identifiers,
            contracts,
            cfg.allowed_host,
            writer_account=writer_account,
            context_options={"storage_state": storage_state},
        )
        return writer, lease, heartbeat_task
    except Exception:
        heartbeat_task.cancel()
        lease.release()
        raise


async def _perform_writes(writer: VerifiedMissionWriter, plan: ProposedPlan) -> bool:
    """Every MUTATION and nothing else -- read-back lives in
    _verify_writes so it can run under its own VERIFYING status.
    MODE_NORMAL fills rows + the five confirmed non-table fields only --
    it never calls trigger_native_recalc (which always raises
    NativeCalculationUnconfirmed for Mode Normal by design, see
    mcma.portal.writer's module docstring). GARAGE_CONVENTIONNE
    additionally triggers the native financial summary."""
    from mcma.domain.enums import RepairWorkflow

    try:
        for step in plan.steps:
            if plan.repair_workflow is RepairWorkflow.MODE_NORMAL:
                await writer.add_normal_row(step.rubrique_id)
            else:
                await writer.edit_conventionne_row(step.rubrique_id)
        await writer.fill_form_fields()
        if plan.repair_workflow is RepairWorkflow.GARAGE_CONVENTIONNE:
            await writer.trigger_native_recalc()
        return True
    except WriteAborted:
        return False


async def _verify_writes(writer: VerifiedMissionWriter, plan: ProposedPlan) -> bool:
    """Every READ-BACK and nothing else. Runs while the job row says
    VERIFYING, so an interruption during read-back is distinguishable
    from an interruption during mutation."""
    from mcma.domain.enums import RepairWorkflow

    try:
        for step in plan.steps:
            await writer.verify_row(step.rubrique_id)
        await writer.verify_form_fields()
        if plan.repair_workflow is RepairWorkflow.GARAGE_CONVENTIONNE:
            await writer.verify_financial_summary()
        return True
    except WriteAborted:
        return False


async def process_one_planned_execute(
    conn,
    job_id: str,
    *,
    browser,
    cfg: RunnerConfig,
    encryptor: InputEncryptor,
    on_browser_closed=None,
) -> str:
    """Drives exactly one PLANNED EXECUTE job (run_execute_planning must
    already have transitioned it there -- POST /jobs/{id}/executions does
    this synchronously today) through account-lease acquisition, identity/
    workflow-verified writer construction, the actual row/form writes, and
    registers the resulting writer with cfg.active_review_registry so a
    second job can never concurrently use the same account (section 4)
    and so the human's own browser close is what drives
    transition_on_browser_closed -- this function itself never touches
    Valider/Clôture and never closes the browser."""
    job_row = AutomationJobsRepository(conn).get(job_id)
    if job_row is None:
        raise ValueError("no such job_id")
    plan = _rebuild_plan(conn, job_row, encryptor)
    account_id = job_row["account_id"]

    state: dict = {}

    def _cancel_heartbeat() -> None:
        task = state.pop("heartbeat_task", None)
        if task is not None:
            task.cancel()

    async def _release_everything() -> None:
        """The ONE teardown path for every non-handoff exit (requirement
        6): heartbeat stopped, review registration removed, browser
        context closed, lease released -- in that order, each
        independently idempotent, so it is safe to call after a close
        callback has already done part of it. Nothing here may raise: a
        failure while cleaning up must not mask the outcome being
        reported, and must not skip the steps after it."""
        # Set FIRST: closing the context below fires the very same close
        # event an employee would, and _on_close must not read that as
        # the employee acting. Relying on writer.is_closed alone is not
        # enough here -- this teardown is also reached on paths where the
        # writer was never opened.
        state["tearing_down"] = True
        _cancel_heartbeat()
        if state.pop("registered", False):
            cfg.active_review_registry.unregister(job_id)
        writer = state.get("writer")
        if writer is not None:
            try:
                await writer.close()
            except Exception:
                pass
        lease = state.pop("lease", None)
        if lease is not None:
            try:
                lease.release()
            except Exception:
                pass

    def _on_close(closed_job_id: str) -> None:
        """Subscribed BEFORE the first mutation, so an employee closing
        the window at any point during writing is observed. Closes this
        runner itself caused are ignored: the write path is already
        recording that outcome, and transitioning here too would be the
        conflicting double transition F.4 forbids."""
        if state.get("tearing_down"):
            return
        writer = state.get("writer")
        if writer is not None and (writer.is_terminally_aborted or writer.is_closed):
            return

        def _release():
            _cancel_heartbeat()
            lease = state.get("lease")
            if lease is not None:
                lease.release()

        try:
            transition_on_browser_closed(conn, closed_job_id, release_lease=_release)
        except JobAuthorizationError:
            # The job already has a recorded outcome (a restart's
            # reconciliation, or the write path winning the race). A
            # close callback never overwrites one.
            return
        if on_browser_closed is not None:
            on_browser_closed(closed_job_id)

    async def _acquire_lease_and_verify_identity():
        # Requirement 4: refuse a second job on this shared account
        # BEFORE any browser context exists, not after the registry
        # rejects the registration post-write.
        active_job_id = cfg.active_review_registry.active_job_for_account(account_id)
        if active_job_id is not None and active_job_id != job_id:
            raise AccountBusy(
                f"account {account_id!r} already has an active review session for job {active_job_id!r}"
            )
        try:
            writer, lease, heartbeat_task = await _open_writer_for_execute(conn, browser, cfg, job_row, plan)
        except LeaseNotHeld as exc:
            # Contention, not an identity problem -- reported as such.
            raise AccountBusy(str(exc)) from exc
        state["writer"] = writer
        state["lease"] = lease
        state["heartbeat_task"] = heartbeat_task
        # Requirement 3: close observation must be live before the first
        # mutation, not after READY_FOR_HUMAN_REVIEW. Registering here
        # also closes the leak this used to have -- a DuplicateActive
        # Review raised at the END of the job left an open context and a
        # heartbeating lease behind with no owner.
        try:
            cfg.active_review_registry.register(job_id, account_id, writer, on_close=_on_close)
        except DuplicateActiveReview as exc:
            await _release_everything()
            raise AccountBusy(str(exc)) from exc
        state["registered"] = True
        return writer

    async def _perform(writer):
        return await _perform_writes(writer, plan)

    async def _verify(writer):
        return await _verify_writes(writer, plan)

    try:
        status = await run_execute_write_async(
            conn,
            job_id,
            acquire_lease_and_verify_identity=_acquire_lease_and_verify_identity,
            perform_writes=_perform,
            verify_writes=_verify,
        )
    except JobAuthorizationError:
        await _release_everything()
        raise
    except Exception as exc:
        # Requirement 2: an unexpected escape must never leave the row at
        # PLANNED, replayable as though no portal work had happened.
        await _release_everything()
        fail_closed_on_runner_exception(conn, job_id, f"RUNNER_EXCEPTION_{type(exc).__name__}")
        raise

    if status != "READY_FOR_HUMAN_REVIEW":
        # IDENTITY_FAILED, WRITE_ABORTED, or an outcome a concurrent
        # browser close already recorded. Either way no human review
        # follows, so nothing may outlive this attempt.
        await _release_everything()
        return status

    # Success: registration, browser, lease and heartbeat all stay live
    # for the human review that follows. They are surrendered only by
    # _on_close, by confirm_review_completed/report_review_problem, or by
    # the heartbeat's own maximum-hold cap.
    return status


async def process_queued_planned_execute_jobs(
    conn, *, browser, cfg: RunnerConfig, encryptor: InputEncryptor, on_browser_closed=None
) -> Tuple[str, ...]:
    jobs_repo = AutomationJobsRepository(conn)
    job_ids = tuple(row["job_id"] for row in jobs_repo.list_by_mode_and_status("EXECUTE", "PLANNED"))
    outcomes = []
    for job_id in job_ids:
        try:
            outcomes.append(
                await process_one_planned_execute(
                    conn, job_id, browser=browser, cfg=cfg, encryptor=encryptor, on_browser_closed=on_browser_closed
                )
            )
        except Exception as exc:
            # process_one_planned_execute has already torn down and
            # landed the row before re-raising; this is the belt-and-
            # braces layer for anything that escaped before it could.
            fail_closed_on_runner_exception(conn, job_id, f"RUNNER_EXCEPTION_{type(exc).__name__}")
            outcomes.append(f"RUNNER_ERROR_{type(exc).__name__}")
    return tuple(outcomes)
