"""
Pilot-integration correction (section 7) -- real-Chromium proof for the
five confirmed non-table header fields (Kilometrage, ValeurVenale/
Estime, NbreJourImmobilisation, PartResponsabilite, ObservationMission):
real DOM fill via fill_form_fields() (Playwright .fill()/.select_option(),
dispatching real input/change events), an INDEPENDENT fresh DOM read-back
via verify_form_fields(), and a read-back-mismatch negative control
paired with the exact same positive control in the same guarded context.
Exercised against BOTH Mode Normal and Garage Conventionne missions,
since PORTAL_CONTRACT.md §4-5 documents these as shared header fields
present regardless of workflow.
"""

import pytest

from mcma.domain.enums import FormFieldSelector, RepairWorkflow
from mcma.domain.values import FormFieldIntent
from mcma.portal.capabilities import SearchIdentifiers
from mcma.portal.writer import RowReadBackMismatch, WriterPlanData, open_verified_writer
from writer_live_chromium_test_support import ALLOWED_HOST, live_mock_server  # noqa: F401
from writer_test_support import (
    MCMA_WRITER_ACCOUNT,
    NORMAL_READ_ROWS_CONTRACT,
    NORMAL_ROW_WRITE_CONTRACT,
    PEC_READ_ROWS_CONTRACT,
    PEC_ROW_WRITE_CONTRACT,
    SEARCH_LISTE_MISSIONS_CONTRACT,
    SEARCH_PAGE_CONTRACT,
    SyntheticLeaseHandle,
    make_expected_identity,
    row_intent,
    run_async,
)

pytestmark = [pytest.mark.egress_proof, pytest.mark.requires_egress_isolation]

NORMAL_CONTRACTS = (SEARCH_PAGE_CONTRACT, SEARCH_LISTE_MISSIONS_CONTRACT, NORMAL_READ_ROWS_CONTRACT, NORMAL_ROW_WRITE_CONTRACT)
NORMAL_IDENTITY = make_expected_identity("77001-C-3", "699001")
NORMAL_IDENTIFIERS = SearchIdentifiers(matricule="77001-C-3")

PEC_CONTRACTS = (SEARCH_PAGE_CONTRACT, SEARCH_LISTE_MISSIONS_CONTRACT, PEC_READ_ROWS_CONTRACT, PEC_ROW_WRITE_CONTRACT)
PEC_IDENTITY = make_expected_identity("34602-B-7", "534660")
PEC_IDENTIFIERS = SearchIdentifiers(matricule="34602-B-7")

_FORM_FIELD_INTENTS = (
    FormFieldIntent(FormFieldSelector.KILOMETRAGE, "42000", (RepairWorkflow.MODE_NORMAL, RepairWorkflow.GARAGE_CONVENTIONNE)),
    FormFieldIntent(FormFieldSelector.VALEUR_VENALE, "95000", (RepairWorkflow.MODE_NORMAL, RepairWorkflow.GARAGE_CONVENTIONNE)),
    FormFieldIntent(FormFieldSelector.VALEUR_VENALE_ESTIME, "95000", (RepairWorkflow.MODE_NORMAL, RepairWorkflow.GARAGE_CONVENTIONNE)),
    FormFieldIntent(FormFieldSelector.NBRE_JOUR_IMMOBILISATION, "5", (RepairWorkflow.MODE_NORMAL, RepairWorkflow.GARAGE_CONVENTIONNE)),
    FormFieldIntent(FormFieldSelector.PART_RESPONSABILITE, "50", (RepairWorkflow.MODE_NORMAL, RepairWorkflow.GARAGE_CONVENTIONNE)),
    FormFieldIntent(FormFieldSelector.OBSERVATION_MISSION, "Sinistre synthetique de test.", (RepairWorkflow.MODE_NORMAL, RepairWorkflow.GARAGE_CONVENTIONNE)),
)


def _normal_plan():
    return WriterPlanData(
        repair_workflow=RepairWorkflow.MODE_NORMAL,
        row_intents=(row_intent("3", "10.00", "2.00"),),
        form_field_intents=_FORM_FIELD_INTENTS,
    )


def _pec_plan():
    return WriterPlanData(
        repair_workflow=RepairWorkflow.GARAGE_CONVENTIONNE,
        row_intents=(row_intent("3", "10.00", "2.00", "1.00"),),
        form_field_intents=_FORM_FIELD_INTENTS,
    )


async def _open_normal_writer(browser):
    return await open_verified_writer(
        browser, SyntheticLeaseHandle(), NORMAL_IDENTITY, _normal_plan(), NORMAL_IDENTIFIERS, NORMAL_CONTRACTS, ALLOWED_HOST,
        writer_account=MCMA_WRITER_ACCOUNT,
    )


async def _open_pec_writer(browser):
    return await open_verified_writer(
        browser, SyntheticLeaseHandle(), PEC_IDENTITY, _pec_plan(), PEC_IDENTIFIERS, PEC_CONTRACTS, ALLOWED_HOST,
        writer_account=MCMA_WRITER_ACCOUNT,
    )


def test_mode_normal_form_fields_fill_and_verify(live_mock_server):
    run_async(_fill_and_verify_scenario(_open_normal_writer))


def test_garage_conventionne_form_fields_fill_and_verify(live_mock_server):
    run_async(_fill_and_verify_scenario(_open_pec_writer))


async def _fill_and_verify_scenario(open_writer):
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            writer = await open_writer(browser)
            page = writer._page

            await writer.fill_form_fields()

            # Independent positive control: read every field DIRECTLY
            # from the real DOM (never through the writer's own
            # verify_form_fields yet), proving the fill genuinely
            # happened on the page, not merely that verify_form_fields
            # would trivially agree with itself.
            observed = await page.evaluate(
                """() => ({
                    Kilometrage: document.getElementById('Kilometrage').value,
                    ValeurVenale: document.getElementById('ValeurVenale').value,
                    ValeurVenaleEstime: document.getElementById('ValeurVenaleEstime').value,
                    NbreJourImmobilisation: document.getElementById('NbreJourImmobilisation').value,
                    PartResponsabilite: document.getElementById('PartResponsabilite').value,
                    ObservationMission: document.getElementById('ObservationMission').value,
                })"""
            )
            assert observed == {
                "Kilometrage": "42000",
                "ValeurVenale": "95000",
                "ValeurVenaleEstime": "95000",
                "NbreJourImmobilisation": "5",
                "PartResponsabilite": "50",
                "ObservationMission": "Sinistre synthetique de test.",
            }

            # The writer's OWN independent read-back must also succeed.
            await writer.verify_form_fields()
        finally:
            await browser.close()


def test_form_field_read_back_mismatch_terminally_aborts(live_mock_server):
    run_async(_read_back_mismatch_scenario())


async def _read_back_mismatch_scenario():
    from playwright.async_api import async_playwright
    from mcma.portal.writer import WriteAborted

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            writer = await _open_normal_writer(browser)
            page = writer._page

            await writer.fill_form_fields()
            # Corrupt ONE field's DOM value directly (simulating the
            # portal silently reverting/not persisting it) -- never a
            # value verify_form_fields itself wrote.
            await page.evaluate("document.getElementById('Kilometrage').value = '0'")

            with pytest.raises(RowReadBackMismatch):
                await writer.verify_form_fields()

            # Terminally aborted -- no retry, no further page interaction.
            with pytest.raises(WriteAborted):
                await writer.fill_form_fields()

            # Positive control, a FRESH writer/context: the SAME fields
            # genuinely verify successfully when uncorrupted.
            fresh_writer = await _open_normal_writer(browser)
            await fresh_writer.fill_form_fields()
            await fresh_writer.verify_form_fields()
            await fresh_writer.close()
        finally:
            await browser.close()


def test_form_fields_do_not_touch_charge_mutuelle_or_societaire(live_mock_server):
    run_async(_no_charge_field_scenario())


async def _no_charge_field_scenario():
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            writer = await _open_normal_writer(browser)
            page = writer._page

            before = await page.evaluate(
                """() => ({
                    societaire: document.getElementById('MontantChargeSocietaire').value,
                    mutuelle: document.getElementById('MontantChargeMutuelle').value,
                })"""
            )
            await writer.fill_form_fields()
            after = await page.evaluate(
                """() => ({
                    societaire: document.getElementById('MontantChargeSocietaire').value,
                    mutuelle: document.getElementById('MontantChargeMutuelle').value,
                })"""
            )
            assert before == after  # untouched by fill_form_fields
        finally:
            await browser.close()


def test_a_plan_with_no_form_field_intents_is_a_legitimate_no_op(live_mock_server):
    run_async(_no_intents_scenario())


async def _no_intents_scenario():
    from playwright.async_api import async_playwright

    plan = WriterPlanData(repair_workflow=RepairWorkflow.MODE_NORMAL, row_intents=(row_intent("3", "10.00", "2.00"),))
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            writer = await open_verified_writer(
                browser, SyntheticLeaseHandle(), NORMAL_IDENTITY, plan, NORMAL_IDENTIFIERS, NORMAL_CONTRACTS, ALLOWED_HOST,
                writer_account=MCMA_WRITER_ACCOUNT,
            )
            await writer.fill_form_fields()  # never raises
            await writer.verify_form_fields()  # never raises
        finally:
            await browser.close()
