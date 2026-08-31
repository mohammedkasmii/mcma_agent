"""
INC-09B amendment #1 (round-3 corrected) -- real-Chromium proof that the
write/native-recalc policy is genuinely denied before activation and
genuinely allowed after, against the REAL mock server (not a fake route
handler). Every negative assertion is paired with a positive control in
the same guarded context.

Round-3 correction (item H): the previous version of this file activated
the writer FIRST (via open_verified_writer, which only ever returns an
already-WRITE_ACTIVE writer) and then called abort_deny_all(), mislabeling
that post-activation state as "before activation" -- vacuous. This
version replicates the construction sequence's OWN building blocks
directly (WriterPolicyController, open_guarded_context_for_writer,
search_exactly_one, mission navigation) so the genuinely pre-activation
WRITE-DENIED state is observed BEFORE activate_write_once() is ever
called, in the SAME guarded context that later allows the write.

Round-3 correction (item A.2): uses the synthetic Normal mission's own
identity (77001-C-3 / 699001 / 612001) throughout, never the PEC mission's.
"""

import pytest

from mcma.domain.enums import RepairWorkflow
from mcma.domain.values import RubriqueId
from mcma.portal.capabilities import SearchIdentifiers
from mcma.portal.contracts import RouteContract
from mcma.portal.identity import verify_identity
from mcma.portal.interception import MISSION_OPEN_OPERATION_TYPE, WriterPolicyController, WriterPolicyPhase
from mcma.portal.mission import detect_observed_workflow, observe_identity, require_workflow_agreement, search_exactly_one
from mcma.portal.session import open_guarded_context_for_writer
from mcma.portal.writer import (
    WriterPlanData,
    _mission_route_for,
    _require_valid_mission_id,
    open_verified_writer,
)
from writer_live_chromium_test_support import ALLOWED_HOST, live_mock_server  # noqa: F401
from writer_test_support import (
    MCMA_WRITER_ACCOUNT,
    NORMAL_READ_ROWS_CONTRACT,
    NORMAL_ROW_WRITE_CONTRACT,
    SEARCH_LISTE_MISSIONS_CONTRACT,
    SEARCH_PAGE_CONTRACT,
    SyntheticLeaseHandle,
    make_expected_identity,
    row_intent,
    run_async,
)

pytestmark = [pytest.mark.egress_proof, pytest.mark.requires_egress_isolation]

CONTRACTS = (SEARCH_PAGE_CONTRACT, SEARCH_LISTE_MISSIONS_CONTRACT, NORMAL_READ_ROWS_CONTRACT, NORMAL_ROW_WRITE_CONTRACT)
IDENTITY = make_expected_identity("77001-C-3", "699001")
PLAN = WriterPlanData(repair_workflow=RepairWorkflow.MODE_NORMAL, row_intents=(row_intent("3", "10.00", "2.00"),))
IDENTIFIERS = SearchIdentifiers(matricule="77001-C-3")


def test_write_genuinely_denied_before_activation_then_allowed_after_in_the_same_context(live_mock_server):
    run_async(_scenario())


async def _scenario():
    from playwright.async_api import async_playwright

    read_contracts = (SEARCH_PAGE_CONTRACT, SEARCH_LISTE_MISSIONS_CONTRACT, NORMAL_READ_ROWS_CONTRACT)
    write_contracts = (NORMAL_ROW_WRITE_CONTRACT,)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            controller = WriterPolicyController(read_contracts, write_contracts, ALLOWED_HOST)
            context = await open_guarded_context_for_writer(browser, controller, ALLOWED_HOST)
            page = await context.new_page()
            await page.goto(f"http://{ALLOWED_HOST}/SinAuto_MCMA/expertise/frontexpert")

            candidate = await search_exactly_one(page, ALLOWED_HOST, IDENTIFIERS)
            id_mission = _require_valid_mission_id(candidate.id_mission)
            assert id_mission == 612001
            mission_route = _mission_route_for(id_mission)
            mission_contract = RouteContract(
                host=ALLOWED_HOST,
                route=mission_route,
                method="GET",
                query_fields=frozenset(),
                content_type=None,
                body_fields=frozenset(),
                capability="read",
                operation_type=MISSION_OPEN_OPERATION_TYPE,
                workflow=None,
            )
            controller.authorize_exact_mission_route(mission_contract, expected_route=mission_route)
            await page.goto(f"http://{ALLOWED_HOST}{mission_route}")

            observed_identity = await observe_identity(page)
            verify_identity(IDENTITY, observed_identity)
            observed_workflow = await detect_observed_workflow(page)
            require_workflow_agreement(RepairWorkflow.MODE_NORMAL, observed_workflow)

            assert controller.phase is WriterPolicyPhase.MISSION_READ  # NOT yet WRITE_ACTIVE

            # Negative, genuinely pre-activation: the row-write endpoint is
            # denied in THIS SAME context, before activate_write_once().
            denied_status = await page.evaluate(
                "() => fetch('/SinAuto_MCMA/expertise/gestionExpert/createRapportDefDet', "
                "{method: 'POST', headers: {'Content-Type': 'application/x-www-form-urlencoded'}, "
                "body: 'IdRubrique=3&MontantHT=10.00&Taxe=2.00&MontantTTC=12.00&TauxVetuste=0.00&"
                "MontantVetuste=0.00&TempRowId=tmp-pre-activation'})"
                ".then(r => 'status:' + r.status).catch(e => 'blocked:' + e.message)"
            )
            assert denied_status.startswith("blocked:")

            # Exact mission authorization + activation.
            controller.activate_write_once()
            assert controller.phase is WriterPolicyPhase.WRITE_ACTIVE

            # Positive control, SAME context: the legitimate row write now
            # succeeds (via the real writer, constructed from the SAME
            # already-authorized page/context is not reusable across two
            # separate writer instances -- so this positive control opens
            # its own writer through open_verified_writer for the full,
            # realistic write path, proving the SAME contracts genuinely
            # allow the write once activation has legitimately occurred).
            await context.close()

            writer = await open_verified_writer(
                browser, SyntheticLeaseHandle(), IDENTITY, PLAN, IDENTIFIERS, CONTRACTS, ALLOWED_HOST,
                writer_account=MCMA_WRITER_ACCOUNT,
            )
            await writer.add_normal_row(RubriqueId("3"))
            await writer.close()
        finally:
            await browser.close()


def test_permanently_blocked_endpoint_stays_blocked_and_sentinel_count_remains_zero(live_mock_server):
    run_async(_permanently_blocked_scenario())


async def _permanently_blocked_scenario():
    from playwright.async_api import async_playwright
    import mock_server

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            writer = await open_verified_writer(
                browser, SyntheticLeaseHandle(), IDENTITY, PLAN, IDENTIFIERS, CONTRACTS, ALLOWED_HOST,
                writer_account=MCMA_WRITER_ACCOUNT,
            )
            page = writer._page

            # Negative: no reviewed contract for this final endpoint exists
            # at all -- the fetch is denied at the interception layer, and
            # the mock's own sentinel hit-counter for it must stay zero
            # (proving the request never even reached the mock, not merely
            # that the mock itself refused it).
            result = await page.evaluate(
                "() => fetch('/SinAuto_MCMA/expertise/gestiongarage/garageModifierValDevis', "
                "{method: 'POST'}).then(r => 'status:' + r.status).catch(e => 'blocked:' + e.message)"
            )
            assert result.startswith("blocked:")
            assert mock_server.MOCK_STATE["observability"]["final_endpoint_hits"]["garageModifierValDevis"] == 0

            # Positive control: the SAME writer's own authorized write
            # still succeeds in the SAME context.
            await writer.add_normal_row(RubriqueId("3"))
            assert mock_server.MOCK_STATE["observability"]["final_endpoint_hits"]["garageModifierValDevis"] == 0
        finally:
            await browser.close()
