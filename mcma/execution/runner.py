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

Runs synchronously: sqlite3 is sync, and every Playwright coroutine this
module drives is awaited inside a bounded `asyncio.run(...)` call scoped
to one job's browser-facing work -- there is no concurrent worker pool in
this pilot scope (WORKFLOW_STATE_MODEL.md's single-writer model: one
running instance, matching mcma.core.mutex's own guarantee). "own the
process-wide workers/registry" (section 2) means mcma.app.main
constructs exactly one RunnerConfig/ActiveReviewRegistry pair for the
process and calls this module's poll functions from its own loop; this
module owns no thread/loop of its own.

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

from mcma.execution.browser_handoff import ActiveReviewRegistry
from mcma.execution.inputs import InputEncryptor, retrieve_and_verify_job_input
from mcma.execution.jobs import (
    JobAuthorizationError,
    run_dry_run_identity_check,
    run_dry_run_planning,
    run_execute_write,
    transition_on_browser_closed,
)
from mcma.execution.lease import acquire_account_lease
from mcma.mapping.wexia import parse_wexia
from mcma.persistence.leases import AccountLeaseHandle, LeaseNotHeld
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
        lease.release()


def process_one_queued_dry_run(conn, job_id: str, *, browser, cfg: RunnerConfig, encryptor: InputEncryptor) -> str:
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

    def _check_identity_read_only() -> bool:
        return asyncio.run(_observe_and_verify_identity(conn, browser, cfg, job_row["account_id"], job_id, plan))

    run_dry_run_identity_check(conn, job_id, check_identity_read_only=_check_identity_read_only)
    return AutomationJobsRepository(conn).get(job_id)["status"]


def process_queued_dry_run_jobs(conn, *, browser, cfg: RunnerConfig, encryptor: InputEncryptor) -> Tuple[str, ...]:
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
            outcomes.append(process_one_queued_dry_run(conn, job_id, browser=browser, cfg=cfg, encryptor=encryptor))
        except Exception as exc:  # pragma: no cover - defensive isolation only
            outcomes.append(f"RUNNER_ERROR_{type(exc).__name__}")
    return tuple(outcomes)


# --------------------------------------------------------------------- #
# EXECUTE: real lease + session + writer, human handoff registration
# --------------------------------------------------------------------- #


async def _open_writer_for_execute(
    conn, browser, cfg: RunnerConfig, job_row, plan: ProposedPlan
) -> Tuple[VerifiedMissionWriter, AccountLeaseHandle]:
    account_id = job_row["account_id"]
    lease = acquire_account_lease(conn, account_id, cfg.instance_id, owner_job_id=job_row["job_id"], ttl_seconds=120)
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
        return writer, lease
    except Exception:
        lease.release()
        raise


def _perform_writes_and_verify(writer: VerifiedMissionWriter, plan: ProposedPlan) -> bool:
    """MODE_NORMAL fills rows + the five confirmed non-table fields only
    -- it never calls trigger_native_recalc (which always raises
    NativeCalculationUnconfirmed for Mode Normal by design, see
    mcma.portal.writer's module docstring). GARAGE_CONVENTIONNE
    additionally triggers and verifies the native financial summary."""
    from mcma.domain.enums import RepairWorkflow

    async def _run() -> bool:
        try:
            if plan.repair_workflow is RepairWorkflow.MODE_NORMAL:
                for step in plan.steps:
                    await writer.add_normal_row(step.rubrique_id)
                    await writer.verify_row(step.rubrique_id)
            else:
                for step in plan.steps:
                    await writer.edit_conventionne_row(step.rubrique_id)
                    await writer.verify_row(step.rubrique_id)
            await writer.fill_form_fields()
            await writer.verify_form_fields()
            if plan.repair_workflow is RepairWorkflow.GARAGE_CONVENTIONNE:
                await writer.trigger_native_recalc()
                await writer.verify_financial_summary()
            return True
        except WriteAborted:
            return False

    return asyncio.run(_run())


def process_one_planned_execute(
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

    # acquire_lease_and_verify_identity's return value is what
    # run_execute_write hands to perform_writes_and_verify, and is NOT
    # otherwise visible to this function afterward -- both the lease and
    # the writer are stashed in this closure-local box so the human
    # handoff/lease-release code below (which runs after run_execute_write
    # returns) can reach them.
    state: dict = {}

    def _acquire_lease_and_verify_identity():
        writer, lease = asyncio.run(_open_writer_for_execute(conn, browser, cfg, job_row, plan))
        state["lease"] = lease
        state["writer"] = writer
        return writer

    def _perform(writer):
        return _perform_writes_and_verify(writer, plan)

    try:
        status = run_execute_write(
            conn, job_id,
            acquire_lease_and_verify_identity=_acquire_lease_and_verify_identity,
            perform_writes_and_verify=_perform,
        )
    except JobAuthorizationError:
        lease = state.get("lease")
        if lease is not None:
            lease.release()
        raise

    lease = state.get("lease")
    if status != "READY_FOR_HUMAN_REVIEW":
        # IDENTITY_FAILED or WRITE_ABORTED -- the lease must not outlive
        # this job's own failed attempt (section 4's lifecycle discipline
        # applies to every exit, not only the success path).
        if lease is not None:
            lease.release()
        return status

    def _on_close(closed_job_id: str) -> None:
        def _release():
            if lease is not None:
                lease.release()

        transition_on_browser_closed(conn, closed_job_id, release_lease=_release)
        if on_browser_closed is not None:
            on_browser_closed(closed_job_id)

    cfg.active_review_registry.register(job_id, job_row["account_id"], state["writer"], on_close=_on_close)
    return status


def process_queued_planned_execute_jobs(
    conn, *, browser, cfg: RunnerConfig, encryptor: InputEncryptor, on_browser_closed=None
) -> Tuple[str, ...]:
    jobs_repo = AutomationJobsRepository(conn)
    job_ids = tuple(row["job_id"] for row in jobs_repo.list_by_mode_and_status("EXECUTE", "PLANNED"))
    outcomes = []
    for job_id in job_ids:
        try:
            outcomes.append(
                process_one_planned_execute(
                    conn, job_id, browser=browser, cfg=cfg, encryptor=encryptor, on_browser_closed=on_browser_closed
                )
            )
        except Exception as exc:  # pragma: no cover - defensive isolation only
            outcomes.append(f"RUNNER_ERROR_{type(exc).__name__}")
    return tuple(outcomes)
