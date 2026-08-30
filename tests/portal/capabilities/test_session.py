"""
INC-08 -- open_guarded_context: every context is hardened + guarded before
any page is created or navigated. Amendment #4's contract-freeze regression
lives here: mutating the caller's original contracts list after context
creation must not change the installed policy.
"""

import pytest

from capabilities_test_support import (
    ALLOWED_HOST,
    FakeBrowser,
    FakeRequest,
    FakeRoute,
    FailingNewContextBrowser,
    READ_NORMAL_ROWS_CONTRACT,
    run_async,
)
from mcma.portal.session import open_guarded_context


def test_open_guarded_context_hardens_options_and_installs_guard():
    browser = FakeBrowser()
    context = run_async(open_guarded_context(browser, (READ_NORMAL_ROWS_CONTRACT,), ALLOWED_HOST))
    assert browser.new_context_calls[0]["service_workers"] == "block"
    assert len(context.route_calls) == 1
    assert context.route_calls[0][0] == "**/*"
    assert len(context.ws_route_calls) == 1
    assert context.closed_count == 0


def test_open_guarded_context_rejects_conflicting_service_workers_before_creating_context():
    browser = FakeBrowser()
    with pytest.raises(ValueError):
        run_async(
            open_guarded_context(
                browser,
                (READ_NORMAL_ROWS_CONTRACT,),
                ALLOWED_HOST,
                context_options={"service_workers": "allow"},
            )
        )
    assert browser.new_context_calls == []


def test_open_guarded_context_propagates_new_context_failure():
    with pytest.raises(RuntimeError):
        run_async(
            open_guarded_context(
                FailingNewContextBrowser(), (READ_NORMAL_ROWS_CONTRACT,), ALLOWED_HOST
            )
        )


def test_mutating_caller_contract_list_after_creation_does_not_change_installed_policy():
    contracts = [READ_NORMAL_ROWS_CONTRACT]
    browser = FakeBrowser()
    context = run_async(open_guarded_context(browser, contracts, ALLOWED_HOST))
    handler = context.route_calls[0][1]

    # Aggressively mutate the caller's original list AFTER context creation.
    contracts.append(READ_NORMAL_ROWS_CONTRACT)
    contracts.clear()

    allowed_request = FakeRequest(
        url=f"http://{ALLOWED_HOST}/SinAuto_MCMA/expertise/gestionExpert/listeRapportDefDet",
        method="POST",
        headers={"content-type": "application/x-www-form-urlencoded"},
        post_data="",
    )
    route = FakeRoute(allowed_request)
    run_async(handler(route))
    assert route.continued == 1, "installed policy must be immune to caller mutation"
    assert route.aborted == 0
