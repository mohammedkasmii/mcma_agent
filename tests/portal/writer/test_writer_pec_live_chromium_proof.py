"""
INC-09B -- Garage Conventionne / PEC real-Chromium proof: real search+open,
preflight against a fresh read of the mock's own current rows, DOM-driven
edit (pencil -> fill HT/Taxe/MontantVetuste only, never TauxVetuste ->
checkmark), exact HTTP-status+state-field validated updateDevisDet, exact
five-field read-back (HT/TVA/TTC/vetuste rate/vetuste amount), the
confirmed DevisCalculerMontantCharge() native trigger, and
verify_financial_summary()'s independent two-channel comparison across
every distinct failure classification (missing/failed/malformed/
incomplete/stale/mismatch), each via a FRESH writer per amendment #2's
"every failure terminally aborts" requirement.
"""

from decimal import Decimal

import pytest

from mcma.domain.enums import RepairWorkflow
from mcma.domain.values import RubriqueId
from mcma.portal.capabilities import SearchIdentifiers
from mcma.portal.mission import WorkflowMismatch
from mcma.portal.writer import (
    NativeCalculationFailed,
    NativeCalculationIncomplete,
    NativeCalculationMalformed,
    NativeCalculationMismatch,
    NativeCalculationMissing,
    NativeCalculationStale,
    WriteAborted,
    WriterPlanData,
    derive_vetuste_rate,
    open_verified_writer,
)
from writer_live_chromium_test_support import ALLOWED_HOST, live_mock_server  # noqa: F401
from writer_test_support import (
    PEC_NATIVE_RECALC_CONTRACT,
    PEC_ROW_WRITE_CONTRACT,
    SEARCH_LISTE_MISSIONS_CONTRACT,
    SEARCH_PAGE_CONTRACT,
    SyntheticLeaseHandle,
    make_expected_identity,
    money,
    row_intent,
    run_async,
)

pytestmark = [pytest.mark.egress_proof, pytest.mark.requires_egress_isolation]

CONTRACTS = (SEARCH_PAGE_CONTRACT, SEARCH_LISTE_MISSIONS_CONTRACT, PEC_ROW_WRITE_CONTRACT, PEC_NATIVE_RECALC_CONTRACT)
IDENTITY = make_expected_identity("34602-B-7", "534660")
IDENTIFIERS = SearchIdentifiers(matricule="34602-B-7")
PLAN = WriterPlanData(
    repair_workflow=RepairWorkflow.GARAGE_CONVENTIONNE, row_intents=(row_intent("3", "10.00", "2.00", "1.00"),)
)


async def _open_writer_and_preflight(browser):
    writer = await open_verified_writer(
        browser, SyntheticLeaseHandle(), IDENTITY, PLAN, IDENTIFIERS, CONTRACTS, ALLOWED_HOST
    )
    page = writer._page
    rows = await page.evaluate(
        "async () => (await (await fetch('/SinAuto_MCMA/expertise/gestiongarage/listeDevisDet', "
        "{method: 'POST'})).json()).data"
    )
    await writer.preflight_pec_rows(SyntheticLeaseHandle(), rows)
    return writer


def test_pec_row_edit_persists_and_verifies_exact_five_fields_including_derived_rate(live_mock_server):
    run_async(_edit_scenario())


async def _edit_scenario():
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            writer = await _open_writer_and_preflight(browser)
            await writer.edit_conventionne_row(SyntheticLeaseHandle(), RubriqueId("3"))

            page = writer._page
            rows = await page.evaluate(
                "async () => (await (await fetch('/SinAuto_MCMA/expertise/gestiongarage/listeDevisDet', "
                "{method: 'POST'})).json()).data"
            )
            row = next(r for r in rows if str(r["IdRubrique"]) == "3")
            assert money(row["MontantHT"]) == money("10.00")
            assert money(row["Taxe"]) == money("2.00")
            assert money(row["MontantVetuste"]) == money("1.00")

            expected_rate = derive_vetuste_rate(money("1.00"), money("12.00"))
            assert expected_rate == Decimal(row["TauxVetuste"])
        finally:
            await browser.close()


def test_pec_wrong_workflow_plan_fails_construction_before_any_write_paired_with_correct_workflow_succeeding(
    live_mock_server,
):
    run_async(_wrong_workflow_then_correct_scenario())


async def _wrong_workflow_then_correct_scenario():
    from playwright.async_api import async_playwright

    # Negative: a GARAGE_CONVENTIONNE plan against the synthetic
    # MODE_NORMAL mission must fail workflow agreement DURING
    # open_verified_writer's own construction sequence -- before any
    # writer object, and therefore before any write, is ever reachable.
    wrong_identifiers = SearchIdentifiers(matricule="77001-C-3")
    wrong_identity = make_expected_identity("77001-C-3", "699001")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            with pytest.raises(WorkflowMismatch):
                await open_verified_writer(
                    browser, SyntheticLeaseHandle(), wrong_identity, PLAN, wrong_identifiers, CONTRACTS, ALLOWED_HOST
                )

            # Positive control: the SAME plan against the CORRECT
            # (GARAGE_CONVENTIONNE) mission succeeds construction.
            writer = await _open_writer_and_preflight(browser)
            await writer.close()
        finally:
            await browser.close()


# --------------------------------------------------------------------- #
# Financial-summary evidence: success is the positive control; each
# failure mode gets its own FRESH writer (a terminally aborted writer's
# context is closed -- amendment #2's "every failure terminally aborts").
# --------------------------------------------------------------------- #


async def _trigger_via_fresh_writer(browser, simulate: str):
    writer = await _open_writer_and_preflight(browser)
    page = writer._page
    await page.evaluate(
        "([sim]) => { document.getElementById('mockSimulatePec').value = sim; }", [simulate]
    )
    return writer


def test_financial_summary_success_is_the_positive_control(live_mock_server):
    run_async(_success_scenario())


async def _success_scenario():
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            writer = await _trigger_via_fresh_writer(browser, "success")
            await writer.trigger_native_recalc()
            summary = await writer.verify_financial_summary()
            assert summary.montant_charge_mutuelle is not None
        finally:
            await browser.close()


@pytest.mark.parametrize(
    "simulate,expected_exception",
    [
        ("missing", NativeCalculationMissing),
        ("failed", NativeCalculationFailed),
        ("malformed", NativeCalculationMalformed),
        ("incomplete", NativeCalculationIncomplete),
        ("stale", NativeCalculationStale),
    ],
)
def test_financial_summary_trigger_time_failures_each_terminally_abort(
    live_mock_server, simulate, expected_exception
):
    run_async(_trigger_time_failure_scenario(simulate, expected_exception))


async def _trigger_time_failure_scenario(simulate, expected_exception):
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            writer = await _trigger_via_fresh_writer(browser, simulate)
            with pytest.raises(expected_exception):
                await writer.trigger_native_recalc()
            with pytest.raises(WriteAborted):
                await writer.trigger_native_recalc()
        finally:
            await browser.close()


def test_financial_summary_mismatch_detected_at_verify_time_via_independent_dom_read(live_mock_server):
    run_async(_mismatch_scenario())


async def _mismatch_scenario():
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            writer = await _trigger_via_fresh_writer(browser, "mismatch")
            await writer.trigger_native_recalc()  # succeeds -- expected parses fine
            with pytest.raises(NativeCalculationMismatch):
                await writer.verify_financial_summary()
        finally:
            await browser.close()
