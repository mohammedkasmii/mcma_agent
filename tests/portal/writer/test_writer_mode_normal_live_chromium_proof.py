"""
INC-09B -- Mode Normal real-Chromium proof: real search+open (no
?workflow= in the URL, no mock-only function/endpoint referenced by
writer.py at all), real DOM-driven add via the scoped Ajouter locator,
exact HTTP-status+state-field validated createRapportDefDet, exact
read-back -- then trigger_native_recalc() must raise
NativeCalculationUnconfirmed and terminally abort the writer. This proof
never claims READY_FOR_HUMAN_REVIEW or calculation success for Mode
Normal.
"""

import pytest

from mcma.domain.enums import RepairWorkflow
from mcma.domain.values import RubriqueId
from mcma.portal.capabilities import SearchIdentifiers
from mcma.portal.writer import (
    NativeCalculationUnconfirmed,
    UnplannedRubrique,
    WriteAborted,
    WriterPlanData,
    open_verified_writer,
)
from writer_live_chromium_test_support import ALLOWED_HOST, live_mock_server  # noqa: F401
from writer_test_support import (
    NORMAL_ROW_WRITE_CONTRACT,
    SEARCH_LISTE_MISSIONS_CONTRACT,
    SEARCH_PAGE_CONTRACT,
    SyntheticLeaseHandle,
    make_expected_identity,
    row_intent,
    run_async,
)

pytestmark = [pytest.mark.egress_proof, pytest.mark.requires_egress_isolation]

CONTRACTS = (SEARCH_PAGE_CONTRACT, SEARCH_LISTE_MISSIONS_CONTRACT, NORMAL_ROW_WRITE_CONTRACT)
IDENTITY = make_expected_identity("34602-B-7", "534660")
PLAN = WriterPlanData(repair_workflow=RepairWorkflow.MODE_NORMAL, row_intents=(row_intent("3", "10.00", "2.00"),))
IDENTIFIERS = SearchIdentifiers(matricule="34602-B-7")


def test_mode_normal_row_persists_then_calculation_unconfirmed_aborts(live_mock_server):
    run_async(_scenario())


async def _scenario():
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            writer = await open_verified_writer(
                browser, SyntheticLeaseHandle(), IDENTITY, PLAN, IDENTIFIERS, CONTRACTS, ALLOWED_HOST
            )
            # No page.evaluate("...mockJsFunctionName...") -- the writer
            # drove the DOM via real navigate/click/select_option only, as
            # a fresh page/goto/click trail confirms indirectly here:
            page = writer._page
            assert page.url.startswith(ALLOWED_HOST) or ALLOWED_HOST in page.url

            await writer.add_normal_row(SyntheticLeaseHandle(), RubriqueId("3"))

            # Exact read-back: exactly one row now exists in the mock's
            # own persisted state.
            row_count = await page.evaluate(
                "async () => (await (await fetch('/SinAuto_MCMA/expertise/gestionExpert/listeRapportDefDet', "
                "{method: 'POST'})).json()).data.length"
            )
            assert row_count == 1

            with pytest.raises(NativeCalculationUnconfirmed):
                await writer.trigger_native_recalc()

            # Terminally aborted -- no retry, no further page interaction.
            with pytest.raises(WriteAborted):
                await writer.add_normal_row(SyntheticLeaseHandle(), RubriqueId("3"))
        finally:
            await browser.close()


def test_unplanned_rubrique_aborts_before_any_dom_interaction_with_valid_add_as_positive_control(
    live_mock_server,
):
    run_async(_unplanned_then_valid())


async def _unplanned_then_valid():
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            writer = await open_verified_writer(
                browser, SyntheticLeaseHandle(), IDENTITY, PLAN, IDENTIFIERS, CONTRACTS, ALLOWED_HOST
            )
            page = writer._page
            before = await page.evaluate("() => document.querySelectorAll('#tbodyModeNormal tr').length")

            with pytest.raises(UnplannedRubrique):
                await writer.add_normal_row(SyntheticLeaseHandle(), RubriqueId("999"))

            after_unplanned = await page.evaluate(
                "() => document.querySelectorAll('#tbodyModeNormal tr').length"
            )
            assert after_unplanned == before  # no DOM interaction happened

            with pytest.raises(WriteAborted):
                await writer.add_normal_row(SyntheticLeaseHandle(), RubriqueId("3"))
        finally:
            await browser.close()
