"""mcma.portal.workstation_execute -- the ONE portal-owned adapter for the
workstation EXECUTE write path (Phase 1C-C Pass 2A).

Only this module (besides mcma.portal.writer/browser/session themselves)
launches Chromium, constructs a browser/context/page, constructs a
VerifiedMissionWriter, interacts with portal pages, or retains the visible
human-review browser for this pipeline. mcma.app.workstation_runner's
job_worker.py/execute_executor.py never import Playwright or
VerifiedMissionWriter (see their own module docstrings and
tests/app/workstation_runner/test_import_isolation.py); the composition
root (mcma.app.workstation_runner.app) is the only caller of this module,
and it hands this module already-converted portal-layer arguments
(WriterPlanData, ExpectedIdentity, SearchIdentifiers, RouteContract) --
never a mcma.planning.plan.ProposedPlan, which this layer is not allowed
to import (persistence/portal may import only domain and core).

Event-loop lifetime (requirement C): run_workstation_execute_write does
not return until either (a) the write failed closed before reaching
human review, or (b) the review browser has been closed (by the employee,
or by this same call's own `should_stop` signal) -- the automation, the
caller's own "report finish to the server" step (`on_ready_for_review`),
and the human-review wait therefore all run on the ONE event loop this
coroutine is awaited on. No Playwright object is ever hand back to a
caller whose event loop might close before it is done being used.

Reuses VerifiedMissionWriter and the SAME row-write/verify orchestration
mcma.execution.runner's own _perform_writes/_verify_writes use for the
central-server EXECUTE path (mode dispatch, native-recalc-only-for-PEC,
WriteAborted-is-the-only-expected-failure) -- duplicated here rather than
imported because mcma.execution (and everything it pulls in --
mcma.persistence, sqlite3) is off-limits to the mcma.app.workstation_runner
package this module is called from (test_import_isolation.py's
_FULL_FORBIDDEN list forbids mcma.execution/mcma.persistence even for
app.py, the one module allowed to import mcma.portal at all)."""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, Sequence

from mcma.domain.enums import RepairWorkflow
from mcma.portal.browser import launch_browser
from mcma.portal.capabilities import LeaseHandle, SearchIdentifiers
from mcma.portal.contracts import RouteContract
from mcma.portal.identity import ExpectedIdentity, IdentityMismatch
from mcma.portal.writer import (
    McmaWriterAccountContext,
    RowAmbiguous,
    UnmatchedRubrique,
    VerifiedMissionWriter,
    WriteAborted,
    WriterPlanData,
    open_verified_writer,
)

# Fixed, non-configurable -- mirrors mcma.app.runners.dispatch.
# EXECUTE_DISPATCH_ENABLED's own discipline: a plain module constant,
# never a parameter, environment variable, or config value read at
# runtime by any composition root. Mode Normal's native
# financial-recalculation contract is explicitly UNCONFIRMED
# (docs/architecture/PORTAL_ROW_WORKFLOWS.md section 3.1; docs/
# implementation/RELEASE_GATES.md's G5) -- flipped only by a future
# reviewed increment once that evidence is confirmed. The ONLY caller
# permitted to override it is a loopback/mock test that must exercise
# Mode Normal's existing add-row behavior against the mock (requirement
# H); no composition root ever passes an override.
MODE_NORMAL_NATIVE_CALCULATION_CONFIRMED = False

WRITE_OUTCOME_READY_FOR_HUMAN_REVIEW = "READY_FOR_HUMAN_REVIEW"
WRITE_OUTCOME_IDENTITY_FAILED = "IDENTITY_FAILED"
WRITE_OUTCOME_WRITE_ABORTED = "WRITE_ABORTED"

# Fixed phase names this module reports through `on_phase` -- never a
# free-form string, so a caller can dispatch on a closed, known set
# without inspecting arbitrary text.
PHASE_WRITING = "WRITING"
PHASE_VERIFYING = "VERIFYING"

OnPhase = Callable[[str], None]
OnReadyForReview = Callable[[], Awaitable[None]]


class PortalReviewSession:
    """Narrow, non-Playwright review-session tracker (requirement D):
    exposes only whether the browser is still open and a way to wait for
    it to close. Never exposes page, context, request, route, or the
    writer itself. Used internally by run_workstation_execute_write only
    -- it is never handed across an asyncio.run() boundary (see the
    module docstring's event-loop-lifetime note), so it never needs to be
    usable from a different event loop than the one that created it.

    The close callback registered with the writer (requirement D) only
    sets an asyncio.Event -- it performs no I/O, no HTTP call, and no
    awaiting of its own, so it is always safe for Playwright to invoke it
    synchronously from inside its own event dispatch."""

    def __init__(self, writer: VerifiedMissionWriter) -> None:
        self._closed_event = asyncio.Event()
        writer.register_close_callback(self._on_browser_closed)

    def _on_browser_closed(self) -> None:
        self._closed_event.set()

    @property
    def is_active(self) -> bool:
        return not self._closed_event.is_set()

    async def wait_until_closed(self) -> None:
        """Waits for the employee to close the browser. An application
        shutdown (requirement F: "application shutdown should close the
        browser and attempt the same fenced close report") is handled by
        the CALLER cancelling the asyncio task this coroutine is running
        on -- that cancellation propagates through this await exactly
        like any other, into run_workstation_execute_write's own
        finally-block close, so no separate should_stop signal is needed
        here."""
        await self._closed_event.wait()


async def _safe_close(writer: VerifiedMissionWriter) -> None:
    try:
        if not writer.is_closed:
            await writer.close()
    except Exception:
        pass


async def _perform_writes(writer: VerifiedMissionWriter, writer_plan: WriterPlanData) -> bool:
    """Every MUTATION and nothing else -- mirrors mcma.execution.runner's
    own _perform_writes exactly, retyped to WriterPlanData's row_intents
    (a portal-native type) instead of a planning-layer ProposedPlan's
    steps, since this module may not import mcma.planning."""
    try:
        for intent in writer_plan.row_intents:
            if writer_plan.repair_workflow is RepairWorkflow.MODE_NORMAL:
                await writer.add_normal_row(intent.rubrique_id)
            else:
                await writer.edit_conventionne_row(intent.rubrique_id)
        await writer.fill_form_fields()
        if writer_plan.repair_workflow is RepairWorkflow.GARAGE_CONVENTIONNE:
            await writer.trigger_native_recalc()
        return True
    except WriteAborted:
        return False


async def _verify_writes(writer: VerifiedMissionWriter, writer_plan: WriterPlanData) -> bool:
    """Every READ-BACK and nothing else -- mirrors mcma.execution.runner's
    own _verify_writes exactly (see _perform_writes's docstring)."""
    try:
        for intent in writer_plan.row_intents:
            await writer.verify_row(intent.rubrique_id)
        await writer.verify_form_fields()
        if writer_plan.repair_workflow is RepairWorkflow.GARAGE_CONVENTIONNE:
            await writer.verify_financial_summary()
        return True
    except WriteAborted:
        return False


async def run_workstation_execute_write(
    storage_state: dict,
    *,
    expected_identity: ExpectedIdentity,
    writer_plan: WriterPlanData,
    identifiers: SearchIdentifiers,
    contracts: Sequence[RouteContract],
    allowed_host: str,
    writer_account: McmaWriterAccountContext,
    permit: LeaseHandle,
    on_ready_for_review: OnReadyForReview,
    on_phase: OnPhase = lambda phase: None,
    mode_normal_native_calculation_confirmed: bool = MODE_NORMAL_NATIVE_CALCULATION_CONFIRMED,
) -> str:
    """Returns exactly one of WRITE_OUTCOME_READY_FOR_HUMAN_REVIEW,
    WRITE_OUTCOME_IDENTITY_FAILED, or WRITE_OUTCOME_WRITE_ABORTED -- the
    narrow subset mcma.app.workstation_runner.execute_executor's
    WRITER_ALLOWED_RESULTS accepts from an injected write callable. Any
    other exception (a construction/config error such as
    AccountNotMcmaWritable or a non-loopback allowed_host, or anything
    unexpected) is left to propagate -- the caller (execute_executor.
    run_execute_check) converts that to INTERNAL_EXECUTION_ERROR, never a
    guess at a more specific outcome.

    1. Opens a VISIBLE (headless=False) Chromium browser and constructs a
       VerifiedMissionWriter against `permit` as the lease handle -- every
       mutation VerifiedMissionWriter performs rechecks `permit.
       assert_valid()` before and after, exactly as it already does for
       every other lease handle it is given (writer.py is unchanged).
    2. Refuses Mode Normal before its first mutation unless the caller has
       explicitly confirmed the native-calculation contract (requirement
       H) -- never adds rows and discovers the gap afterward.
    3. Performs every write, then every read-back verification -- WriteAborted
       (or the employee closing the browser mid-write, detected via the
       SAME close tracker used for human review) fails closed to
       WRITE_ABORTED, closing the writer/context.
    4. On success, calls `on_ready_for_review()` (the caller's own
       "report finish to the server, stop lease renewal" step) BEFORE
       waiting for the browser to close -- both happen on this same
       coroutine/event loop.
    5. Waits for the browser to close (employee-driven, or this
       coroutine's own task being cancelled by the caller on application
       shutdown), then closes the writer/context itself and returns."""
    async with launch_browser(headless=False) as browser:
        try:
            writer = await open_verified_writer(
                browser,
                permit,
                expected_identity,
                writer_plan,
                identifiers,
                contracts,
                allowed_host,
                writer_account=writer_account,
                context_options={"storage_state": storage_state},
            )
        except (IdentityMismatch, RowAmbiguous, UnmatchedRubrique):
            # Identity, or PEC row-matching, failed verification before
            # any browser-context write policy was ever activated --
            # open_verified_writer's own factory has already aborted and
            # closed the context. No mutation occurred.
            return WRITE_OUTCOME_IDENTITY_FAILED

        review = PortalReviewSession(writer)
        try:
            if (
                writer_plan.repair_workflow is RepairWorkflow.MODE_NORMAL
                and not mode_normal_native_calculation_confirmed
            ):
                # Fixed, typed refusal BEFORE any mutation -- requirement
                # H: never add rows first and discover the missing native-
                # calculation contract at the end.
                return WRITE_OUTCOME_WRITE_ABORTED

            on_phase(PHASE_WRITING)
            wrote_ok = await _perform_writes(writer, writer_plan)
            if not wrote_ok or not review.is_active:
                # `not review.is_active` covers the employee closing the
                # browser mid-write without the write path itself raising
                # WriteAborted -- also fails closed.
                return WRITE_OUTCOME_WRITE_ABORTED

            on_phase(PHASE_VERIFYING)
            verified_ok = await _verify_writes(writer, writer_plan)
            if not verified_ok or not review.is_active:
                return WRITE_OUTCOME_WRITE_ABORTED

            # Requirements 7-8: report finish to the server, then keep the
            # browser open for the employee -- on this SAME event loop.
            await on_ready_for_review()

            await review.wait_until_closed()
            return WRITE_OUTCOME_READY_FOR_HUMAN_REVIEW
        finally:
            await _safe_close(writer)
