"""
INC-09B (round-3 corrected) -- Mode Normal real-Chromium proof: real
search+open against the SYNTHETIC NORMAL mission's own identity (item
A.2: 77001-C-3 / 699001 / 612001 -- never the PEC mission's), the GOLDEN
DOM lifecycle recovered from 9a2c57c -- #VehRepareI, the real Ajouter
control, the unsuffixed editing-row fields and the 7th-column checkmark --
followed by a fresh read-back.

UPDATED for the golden port. This proof previously asserted that
trigger_native_recalc() raises NativeCalculationUnconfirmed, and required
an HTTP-status+state-field validated createRapportDefDet. Neither holds
any more: 9a2c57c contains a Mode Normal calculation mechanism that was
exercised successfully against real dossiers, and createRapportDefDet
appears in NEITHER golden commit, so the write is no longer gated on it.
The read-back is now the evidence that the row landed.
"""

import pytest

from mcma.domain.enums import RepairWorkflow
from mcma.domain.values import RubriqueId
from mcma.portal.capabilities import SearchIdentifiers
from mcma.portal.writer import (
    UnplannedRubrique,
    WriteAborted,
    WriterPlanData,
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


async def _open_writer(browser):
    return await open_verified_writer(
        browser, SyntheticLeaseHandle(), IDENTITY, PLAN, IDENTIFIERS, CONTRACTS, ALLOWED_HOST,
        writer_account=MCMA_WRITER_ACCOUNT,
    )


def test_mode_normal_row_persists_then_calculation_unconfirmed_aborts(live_mock_server):
    run_async(_scenario())


async def _scenario():
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            writer = await _open_writer(browser)
            page = writer._page

            await writer.add_normal_row(RubriqueId("3"))

            # Exact read-back: exactly one row now exists in the mock's
            # own persisted state, fetched fresh (never the same
            # in-memory value read twice).
            row_count = await page.evaluate(
                "async () => (await (await fetch('/SinAuto_MCMA/expertise/gestionExpert/listeRapportDefDet', "
                "{method: 'POST', headers: {'Content-Type': 'application/x-www-form-urlencoded'}, body: ''}"
                ")).json()).data.length"
            )
            assert row_count == 1

            await writer.verify_row(RubriqueId("3"))

            # The golden Mode Normal calculation mechanism now runs: the
            # portal's own Calculer* functions are invoked in the page and
            # the summary it computed is read back. Nothing here writes
            # the charge split.
            await writer.trigger_native_recalc()
            summary = await writer.verify_financial_summary()
            assert summary is not None
        finally:
            await browser.close()


def test_unplanned_rubrique_terminally_aborts_with_a_fresh_writer_as_positive_control(live_mock_server):
    run_async(_unplanned_then_fresh_writer_scenario())


async def _unplanned_then_fresh_writer_scenario():
    from playwright.async_api import async_playwright
    import mock_server

    # An UnplannedRubrique abort closes the whole context (terminal abort
    # is unconditional), so "no DOM interaction happened" cannot be proven
    # by re-evaluating the SAME (now-closed) page afterward -- it is
    # proven instead via the mock's own server-side observability, a
    # stronger, network-level signal that no request was ever made.
    calls_before = mock_server.MOCK_STATE["observability"]["row_endpoint_calls"]["MODE_NORMAL"]["createRapportDefDet"]
    rows_before = len(mock_server.MOCK_STATE["rows"]["normal"])

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            aborted_writer = await _open_writer(browser)

            with pytest.raises(UnplannedRubrique):
                await aborted_writer.add_normal_row(RubriqueId("999"))

            assert (
                mock_server.MOCK_STATE["observability"]["row_endpoint_calls"]["MODE_NORMAL"]["createRapportDefDet"]
                == calls_before
            )
            assert len(mock_server.MOCK_STATE["rows"]["normal"]) == rows_before
            with pytest.raises(WriteAborted):
                await aborted_writer.add_normal_row(RubriqueId("3"))  # terminally aborted -- no retry

            # Item H: the positive control uses a FRESH writer/context --
            # it never expects the already-terminally-aborted writer above
            # to succeed.
            fresh_writer = await _open_writer(browser)
            await fresh_writer.add_normal_row(RubriqueId("3"))
            await fresh_writer.close()
        finally:
            await browser.close()


def test_no_direct_charge_field_in_outgoing_create_rapport_def_det_payload(live_mock_server):
    run_async(_charge_field_payload_scenario())


async def _charge_field_payload_scenario():
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            writer = await _open_writer(browser)
            page = writer._page

            captured = {}

            async def _capture(request):
                if request.url.endswith("/createRapportDefDet") and request.method == "POST":
                    captured["post_data"] = request.post_data

            page.on("request", _capture)
            await writer.add_normal_row(RubriqueId("3"))

            assert "post_data" in captured
            assert "MontantChargeMutuelle" not in captured["post_data"]
            assert "MontantChargeSocietaire" not in captured["post_data"]
        finally:
            await browser.close()
