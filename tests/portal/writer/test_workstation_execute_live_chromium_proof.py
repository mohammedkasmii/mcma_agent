"""Phase 1C-C Pass 2A -- real-Chromium proof that
mcma.portal.workstation_execute.run_workstation_execute_write genuinely
drives VerifiedMissionWriter end to end (construction, real row edit,
native recalculation, verification, and the human-review handoff) against
the real loopback mock server -- never a fake writer. Mirrors
tests/portal/writer/test_writer_pec_live_chromium_proof.py's own PEC
mission fixture (34602-B-7 / 534660 / row "3") and reuses this
directory's writer_test_support/writer_live_chromium_test_support exactly
as every other file here does.

Uses the REAL mcma.app.workstation_runner.execution_permit.ExecutionPermit
(not a synthetic lease fake) as the lease handle, proving it satisfies
VerifiedMissionWriter's lease-handle protocol end to end against the real
construction/mutation/read-back lease-recheck calls.

No employee is present to click close in this proof: "browser closed" is
modelled the same truthful way requirement F requires for an application
shutdown -- cancelling the task this coroutine runs on -- which exercises
the SAME real Playwright close path (run_workstation_execute_write's own
finally-block writer.close()) a genuine employee close would."""

import asyncio

import pytest

from mcma.app.workstation_runner.execution_permit import ExecutionPermit
from mcma.domain.enums import RepairWorkflow
from mcma.portal.capabilities import SearchIdentifiers
from mcma.portal.workstation_execute import (
    PHASE_VERIFYING, PHASE_WRITING, run_workstation_execute_write,
)
from mcma.portal.writer import WriterPlanData
from writer_live_chromium_test_support import ALLOWED_HOST, live_mock_server  # noqa: F401
from writer_test_support import (
    MCMA_WRITER_ACCOUNT,
    PEC_NATIVE_RECALC_CONTRACT,
    PEC_READ_ROWS_CONTRACT,
    PEC_ROW_WRITE_CONTRACT,
    SEARCH_LISTE_MISSIONS_CONTRACT,
    SEARCH_PAGE_CONTRACT,
    make_expected_identity,
    row_intent,
    run_async,
)

pytestmark = [pytest.mark.egress_proof, pytest.mark.requires_egress_isolation]

CONTRACTS = (
    SEARCH_PAGE_CONTRACT,
    SEARCH_LISTE_MISSIONS_CONTRACT,
    PEC_READ_ROWS_CONTRACT,
    PEC_ROW_WRITE_CONTRACT,
    PEC_NATIVE_RECALC_CONTRACT,
)
IDENTITY = make_expected_identity("34602-B-7", "534660")
IDENTIFIERS = SearchIdentifiers(matricule="34602-B-7")
PLAN = WriterPlanData(
    repair_workflow=RepairWorkflow.GARAGE_CONVENTIONNE, row_intents=(row_intent("3", "10.00", "2.00", "1.00"),)
)


def test_full_pipeline_reaches_ready_for_human_review_headless_via_real_chromium(live_mock_server):
    run_async(_full_pipeline_scenario())


async def _full_pipeline_scenario():
    import mcma.portal.workstation_execute as we

    # This proof runs headless (like every other test in this package --
    # writer_live_chromium_test_support's own docstring notes production
    # is headful by design, tests are the explicit opt-in exception) --
    # only the browser CONFIGURATION itself (headless=False) is proven
    # separately, via a monkeypatched launch_browser, in
    # tests/portal/test_workstation_execute.py::
    # test_the_browser_is_launched_headless_false, since a real headed
    # browser cannot run in CI. mcma.portal.browser.launch_browser is the
    # SAME reviewed function either way -- only the headless argument
    # this proof passes it differs from what production would pass.
    original_launch_browser = we.launch_browser
    we.launch_browser = lambda *, headless=False: original_launch_browser(headless=True)

    permit = ExecutionPermit(MCMA_WRITER_ACCOUNT.account_id)
    permit.activate()
    phases = []
    reached_review = asyncio.Event()

    async def _on_ready_for_review():
        reached_review.set()

    try:
        task = asyncio.ensure_future(run_workstation_execute_write(
            {"cookies": [], "origins": []},
            expected_identity=IDENTITY,
            writer_plan=PLAN,
            identifiers=IDENTIFIERS,
            contracts=CONTRACTS,
            allowed_host=ALLOWED_HOST,
            writer_account=MCMA_WRITER_ACCOUNT,
            permit=permit,
            on_ready_for_review=_on_ready_for_review,
            on_phase=phases.append,
        ))
        await reached_review.wait()
        assert phases == [PHASE_WRITING, PHASE_VERIFYING]
        # Simulate an application shutdown (requirement F) -- the same
        # real writer.close()/browser.close() path a genuine employee
        # browser-close would take.
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        we.launch_browser = original_launch_browser
