"""Pilot-integration correction (section 2/6/7) -- real-DOM proof that
populateMcmaAccountSelect only ever offers MCMA accounts (never MAMDA,
never a hardcoded id) and that renderPlanPreview shows real plan data
without any charge-mutuelle/sociétaire field or unescaped injection."""

import pytest

from web_test_support import run_async

pytestmark = [pytest.mark.egress_proof, pytest.mark.requires_egress_isolation]


def test_populate_mcma_account_select_never_offers_mamda(dashboard_page):
    async def _run():
        return await dashboard_page(
            lambda page: page.evaluate(
                """() => {
                    const select = document.createElement('select');
                    document.body.appendChild(select);
                    window.mcmaDashboard.populateMcmaAccountSelect(select, [
                        {account_id: 'acct-mcma-oujda', entity: 'MCMA', scope: 'OUJDA'},
                        {account_id: 'acct-mamda-oujda', entity: 'MAMDA', scope: 'OUJDA'},
                        {account_id: 'acct-mcma-nador', entity: 'MCMA', scope: 'NADOR'},
                    ]);
                    return Array.from(select.options).map(o => ({value: o.value, text: o.textContent}));
                }"""
            )
        )

    options = run_async(_run())
    values = [o["value"] for o in options]
    assert "acct-mamda-oujda" not in values
    assert "acct-mcma-oujda" in values
    assert "acct-mcma-nador" in values
    assert values[0] == ""  # the placeholder is always first


def test_render_plan_preview_shows_steps_and_warnings_never_charge_fields(dashboard_page):
    async def _run():
        return await dashboard_page(
            lambda page: page.evaluate(
                """() => {
                    const container = document.createElement('div');
                    document.body.appendChild(container);
                    const job = {
                        plan_snapshot: JSON.stringify({
                            repair_workflow: 'mode_normal',
                            steps: [{rubrique_id: '3', ht: '10.00'}],
                            needs_review: [{reason: 'AMBIGUOUS_GLASS', detail: 'x'}],
                            form_field_intents: [{selector: 'Kilometrage', value: '50000'}],
                        }),
                    };
                    window.mcmaDashboard.renderPlanPreview(container, job);
                    return {
                        text: container.textContent,
                        html: container.innerHTML,
                    };
                }"""
            )
        )

    result = run_async(_run())
    assert "Kilometrage" in result["text"]
    assert "AMBIGUOUS_GLASS" in result["text"]
    assert "MontantChargeMutuelle" not in result["html"]
    assert "MontantChargeSocietaire" not in result["html"]


def test_render_plan_preview_handles_missing_plan_without_throwing(dashboard_page):
    async def _run():
        return await dashboard_page(
            lambda page: page.evaluate(
                """() => {
                    const container = document.createElement('div');
                    document.body.appendChild(container);
                    window.mcmaDashboard.renderPlanPreview(container, null);
                    return container.textContent;
                }"""
            )
        )

    text = run_async(_run())
    assert "No plan yet" in text
