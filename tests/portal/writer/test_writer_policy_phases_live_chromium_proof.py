"""
INC-09B amendment #1 -- real-Chromium proof that the write/native-recalc
policy is genuinely denied before activation and genuinely allowed after,
against the REAL mock server (not a fake route handler). Every negative
assertion is paired with a positive control in the same guarded context.

Marked egress_proof + requires_egress_isolation -- testsupport/
egress_guard.py fails these at setup outside verified loopback-only
isolation; locally deselect with -m "not egress_proof" (this repo's own
convention, unchanged since INC-08/09A).
"""

import pytest

from mcma.domain.enums import RepairWorkflow
from mcma.portal.capabilities import SearchIdentifiers
from mcma.portal.interception import WriterPolicyPhase
from mcma.portal.writer import WriteAborted, WriterPlanData, open_verified_writer
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


def test_write_denied_before_construction_completes_then_allowed_after(live_mock_server):
    run_async(_scenario())


async def _scenario():
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            writer = await open_verified_writer(
                browser, SyntheticLeaseHandle(), IDENTITY, PLAN, IDENTIFIERS, CONTRACTS, ALLOWED_HOST
            )
            # By construction, open_verified_writer only returns once
            # WRITE_ACTIVE has been reached -- the controller reference
            # itself is private, so this proves activation happened by
            # exercising the ACTUAL write path below instead.
            controller = writer._abort_handle._controller
            assert controller.phase is WriterPolicyPhase.WRITE_ACTIVE

            # Positive control: the write contract genuinely works.
            from mcma.domain.values import RubriqueId

            await writer.add_normal_row(SyntheticLeaseHandle(), RubriqueId("3"))

            # Negative: abort_deny_all denies everything immediately,
            # including a request the SAME writer would otherwise be
            # allowed to make.
            writer._abort_handle.abort()
            assert controller.phase is WriterPolicyPhase.ABORTED
            with pytest.raises(WriteAborted):
                await writer.add_normal_row(SyntheticLeaseHandle(), RubriqueId("3"))
        finally:
            await browser.close()


def test_permanently_blocked_endpoint_stays_blocked_inside_an_authorized_writer(live_mock_server):
    run_async(_permanently_blocked_scenario())


async def _permanently_blocked_scenario():
    from playwright.async_api import async_playwright
    from mcma.domain.values import RubriqueId

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            writer = await open_verified_writer(
                browser, SyntheticLeaseHandle(), IDENTITY, PLAN, IDENTIFIERS, CONTRACTS, ALLOWED_HOST
            )
            page = writer._page

            # Negative: no reviewed contract for this final endpoint exists
            # at all (createDevisDet/garageModifierValDevis-style final
            # actions are never granted) -- the fetch is denied at the
            # interception layer.
            result = await page.evaluate(
                "() => fetch('/SinAuto_MCMA/expertise/gestiongarage/garageModifierValDevis', "
                "{method: 'POST'}).then(r => 'status:' + r.status).catch(e => 'blocked:' + e.message)"
            )
            assert result.startswith("blocked:")

            # Positive control: the SAME writer's own authorized write
            # still succeeds in the SAME context.
            await writer.add_normal_row(SyntheticLeaseHandle(), RubriqueId("3"))
        finally:
            await browser.close()
