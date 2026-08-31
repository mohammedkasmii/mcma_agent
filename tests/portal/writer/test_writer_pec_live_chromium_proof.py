"""
INC-09B (round-3 corrected) -- Garage Conventionne / PEC real-Chromium
proof: real search+open, preflight now happens INSIDE
open_verified_writer's construction (no public preflight_pec_rows call
here anymore), DOM-driven edit (pencil -> fill HT/Taxe/MontantVetuste
only, never TauxVetuste -> checkmark), a real fresh-rows
diff-before-write/read-after-write, exact HTTP-status+state-field
validated updateDevisDet, exact read-back (HT/TVA/TTC/vetuste rate/
vetuste amount via verify_row), the confirmed
DevisCalculerMontantCharge() native trigger, and
verify_financial_summary()'s independent two-channel comparison across
every distinct failure classification (missing/failed/malformed/
incomplete/stale/mismatch), each via a FRESH writer per "every failure
terminally aborts."

Item A.2: PEC tests stay on the PEC mission's own identity (34602-B-7 /
534660 / 532805) throughout -- unchanged.
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
    MCMA_WRITER_ACCOUNT,
    PEC_NATIVE_RECALC_CONTRACT,
    PEC_READ_ROWS_CONTRACT,
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


async def _open_writer(browser):
    return await open_verified_writer(
        browser, SyntheticLeaseHandle(), IDENTITY, PLAN, IDENTIFIERS, CONTRACTS, ALLOWED_HOST,
        writer_account=MCMA_WRITER_ACCOUNT,
    )


def test_pec_row_edit_persists_and_verifies_exact_fields_including_derived_rate(live_mock_server):
    run_async(_edit_scenario())


async def _edit_scenario():
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            writer = await _open_writer(browser)
            # Preflight already happened during construction -- proven
            # implicitly: edit_conventionne_row would abort with
            # UnplannedRubrique if the mapping had not been cached.
            await writer.edit_conventionne_row(RubriqueId("3"))
            await writer.verify_row(RubriqueId("3"))  # exact HT/TVA/vetuste/derived-rate re-check

            page = writer._page
            rows = await page.evaluate(
                "async () => (await (await fetch('/SinAuto_MCMA/expertise/gestiongarage/listeDevisDet', "
                "{method: 'POST', headers: {'Content-Type': 'application/x-www-form-urlencoded'}, body: ''}"
                ")).json()).data"
            )
            row = next(r for r in rows if str(r["IdRubrique"]) == "3")
            assert money(row["MontantHT"]) == money("10.00")
            assert money(row["Taxe"]) == money("2.00")
            assert money(row["MontantVetuste"]) == money("1.00")

            expected_rate = derive_vetuste_rate(money("1.00"), money("12.00"))
            assert expected_rate == Decimal(row["TauxVetuste"])
        finally:
            await browser.close()


def test_pec_edit_is_a_no_op_when_already_exactly_equal(live_mock_server):
    run_async(_no_op_scenario())


async def _no_op_scenario():
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            writer = await _open_writer(browser)
            await writer.edit_conventionne_row(RubriqueId("3"))
            page = writer._page
            rows_before = await page.evaluate(
                "async () => (await (await fetch('/SinAuto_MCMA/expertise/gestiongarage/listeDevisDet', "
                "{method: 'POST', headers: {'Content-Type': 'application/x-www-form-urlencoded'}, body: ''}"
                ")).json()).data"
            )
            # Second call with the SAME approved intent must be a silent
            # no-op (diff-before-write), not a second write attempt.
            await writer.edit_conventionne_row(RubriqueId("3"))
            rows_after = await page.evaluate(
                "async () => (await (await fetch('/SinAuto_MCMA/expertise/gestiongarage/listeDevisDet', "
                "{method: 'POST', headers: {'Content-Type': 'application/x-www-form-urlencoded'}, body: ''}"
                ")).json()).data"
            )
            assert rows_before == rows_after
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
    # PLAN's own workflow is GARAGE_CONVENTIONNE, so the contract set must
    # still be the PEC one (contracts_for_workflow filters by the PLAN's
    # workflow, independent of which mission search actually resolves) --
    # only the identity/search target points at the wrong mission.
    wrong_contracts = (SEARCH_PAGE_CONTRACT, SEARCH_LISTE_MISSIONS_CONTRACT, PEC_READ_ROWS_CONTRACT, PEC_ROW_WRITE_CONTRACT)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            with pytest.raises(WorkflowMismatch):
                await open_verified_writer(
                    browser, SyntheticLeaseHandle(), wrong_identity, PLAN, wrong_identifiers, wrong_contracts, ALLOWED_HOST,
                    writer_account=MCMA_WRITER_ACCOUNT,
                )

            # Positive control: the SAME plan against the CORRECT
            # (GARAGE_CONVENTIONNE) mission succeeds construction.
            writer = await _open_writer(browser)
            await writer.close()
        finally:
            await browser.close()


def test_no_direct_charge_field_in_outgoing_update_devis_det_payload(live_mock_server):
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
                if request.url.endswith("/updateDevisDet") and request.method == "POST":
                    captured["post_data"] = request.post_data

            page.on("request", _capture)
            await writer.edit_conventionne_row(RubriqueId("3"))

            assert "post_data" in captured
            assert "DevisMontantChargeMutuelle" not in captured["post_data"]
            assert "DevisMontantChargeSocietaire" not in captured["post_data"]
        finally:
            await browser.close()


# --------------------------------------------------------------------- #
# Financial-summary evidence: success is the positive control; each
# failure mode gets its own FRESH writer ("every failure terminally
# aborts"). The read_rows contract is now present, so every scenario
# reaches the actual calculation code rather than failing earlier on an
# omitted read contract.
# --------------------------------------------------------------------- #


async def _trigger_via_fresh_writer(browser, simulate: str):
    writer = await _open_writer(browser)
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


def test_financial_summary_stale_terminally_aborts_relative_to_a_genuine_prior_calculation(live_mock_server):
    run_async(_stale_scenario())


async def _stale_scenario():
    """"Stale" is only meaningful relative to a REAL prior calculation --
    a fresh writer's very first trigger has no earlier version to be
    stale against. This primes with one genuine simulate=success trigger
    (establishing a real calculation_version), then switches to
    simulate=stale for the second trigger, which must be detected as
    stale relative to that real prior evidence."""
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            writer = await _open_writer(browser)
            await writer.trigger_native_recalc()  # simulate=success by default
            await writer._page.evaluate(
                "([sim]) => { document.getElementById('mockSimulatePec').value = sim; }", ["stale"]
            )
            with pytest.raises(NativeCalculationStale):
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
