"""
INC-09B amendment #1 -- WriterPolicyController explicit-phase state
machine: SEARCH_READ -> MISSION_READ -> WRITE_ACTIVE, or any non-ABORTED
phase -> ABORTED. Replaces the earlier (rejected) general widen() design:
there is no operation here that replaces or arbitrarily widens the active
contract set.

No real Playwright browser anywhere in this file -- FakeContext (from
portal_test_support.py) implements only the async methods
mcma.portal.interception calls.
"""

import pytest

from mcma.portal.contracts import RouteContract
from mcma.portal.interception import (
    AbortOnlyHandle,
    PolicyPhaseError,
    WriterPolicyController,
    WriterPolicyPhase,
    install_phased_portal_guard,
)
from portal_test_support import FakeContext, FakeRequest, FakeRoute, run_async

ALLOWED_HOST = "127.0.0.1:8080"

SEARCH_CONTRACT = RouteContract(
    host=ALLOWED_HOST,
    route="/SinAuto_MCMA/expertise/FrontExpert/listeMissions",
    method="POST",
    query_fields=frozenset(),
    content_type="application/x-www-form-urlencoded",
    body_fields=frozenset({"Matricule", "ReferenceCie"}),
    capability="read",
    operation_type="search",
    workflow=None,
)

WRITE_CONTRACT = RouteContract(
    host=ALLOWED_HOST,
    route="/SinAuto_MCMA/expertise/gestionExpert/createRapportDefDet",
    method="POST",
    query_fields=frozenset(),
    content_type="application/x-www-form-urlencoded",
    body_fields=frozenset(
        {"IdRubrique", "MontantHT", "Taxe", "MontantTTC", "TauxVetuste", "MontantVetuste", "TempRowId"}
    ),
    capability="row_write",
    operation_type="add_row",
    workflow="MODE_NORMAL",
)

MISSION_ROUTE = "/SinAuto_MCMA/expertise/gestionExpert/getSinistre/idSinistre/532805/rubrique/gestionexpert-index"

MISSION_CONTRACT = RouteContract(
    host=ALLOWED_HOST,
    route=MISSION_ROUTE,
    method="GET",
    query_fields=frozenset(),
    content_type=None,
    body_fields=frozenset(),
    capability="read",
    operation_type="mission_open",
    workflow=None,
)


def _new_controller():
    return WriterPolicyController(
        search_read_contracts=(SEARCH_CONTRACT,),
        frozen_write_contracts=(WRITE_CONTRACT,),
        allowed_host=ALLOWED_HOST,
    )


# --------------------------------------------------------------------- #
# Permitted transitions
# --------------------------------------------------------------------- #


def test_initial_phase_is_search_read_with_only_search_contracts():
    controller = _new_controller()
    assert controller.phase is WriterPolicyPhase.SEARCH_READ
    assert controller.contracts() == (SEARCH_CONTRACT,)


def test_authorize_exact_mission_route_transitions_to_mission_read():
    controller = _new_controller()
    controller.authorize_exact_mission_route(MISSION_CONTRACT, expected_route=MISSION_ROUTE)
    assert controller.phase is WriterPolicyPhase.MISSION_READ
    assert MISSION_CONTRACT in controller.contracts()
    assert SEARCH_CONTRACT in controller.contracts()
    assert WRITE_CONTRACT not in controller.contracts()


def test_activate_write_once_transitions_to_write_active_and_exposes_frozen_contracts():
    controller = _new_controller()
    controller.authorize_exact_mission_route(MISSION_CONTRACT, expected_route=MISSION_ROUTE)
    controller.activate_write_once()
    assert controller.phase is WriterPolicyPhase.WRITE_ACTIVE
    assert WRITE_CONTRACT in controller.contracts()
    assert controller.frozen_write_contracts == (WRITE_CONTRACT,)


@pytest.mark.parametrize(
    "starting_phase_setup",
    ["search_read", "mission_read", "write_active"],
)
def test_abort_deny_all_transitions_from_any_non_aborted_phase(starting_phase_setup):
    controller = _new_controller()
    if starting_phase_setup in ("mission_read", "write_active"):
        controller.authorize_exact_mission_route(MISSION_CONTRACT, expected_route=MISSION_ROUTE)
    if starting_phase_setup == "write_active":
        controller.activate_write_once()
    controller.abort_deny_all()
    assert controller.phase is WriterPolicyPhase.ABORTED
    assert controller.contracts() == ()


def test_abort_deny_all_is_idempotent_when_already_aborted():
    controller = _new_controller()
    controller.abort_deny_all()
    controller.abort_deny_all()  # must not raise
    assert controller.phase is WriterPolicyPhase.ABORTED
    assert controller.contracts() == ()


# --------------------------------------------------------------------- #
# Forbidden transitions
# --------------------------------------------------------------------- #


def test_activate_write_once_from_search_read_is_forbidden():
    controller = _new_controller()
    with pytest.raises(PolicyPhaseError):
        controller.activate_write_once()
    assert controller.phase is WriterPolicyPhase.SEARCH_READ


def test_authorize_exact_mission_route_twice_is_forbidden():
    controller = _new_controller()
    controller.authorize_exact_mission_route(MISSION_CONTRACT, expected_route=MISSION_ROUTE)
    with pytest.raises(PolicyPhaseError):
        controller.authorize_exact_mission_route(MISSION_CONTRACT, expected_route=MISSION_ROUTE)
    assert controller.phase is WriterPolicyPhase.MISSION_READ


def test_activate_write_once_twice_is_forbidden():
    controller = _new_controller()
    controller.authorize_exact_mission_route(MISSION_CONTRACT, expected_route=MISSION_ROUTE)
    controller.activate_write_once()
    with pytest.raises(PolicyPhaseError):
        controller.activate_write_once()
    assert controller.phase is WriterPolicyPhase.WRITE_ACTIVE


def test_mission_authorization_after_activation_is_forbidden():
    controller = _new_controller()
    controller.authorize_exact_mission_route(MISSION_CONTRACT, expected_route=MISSION_ROUTE)
    controller.activate_write_once()
    with pytest.raises(PolicyPhaseError):
        controller.authorize_exact_mission_route(MISSION_CONTRACT, expected_route=MISSION_ROUTE)


@pytest.mark.parametrize("call", ["authorize", "activate"])
def test_mutating_calls_after_abort_are_forbidden(call):
    controller = _new_controller()
    controller.abort_deny_all()
    with pytest.raises(PolicyPhaseError):
        if call == "authorize":
            controller.authorize_exact_mission_route(MISSION_CONTRACT, expected_route=MISSION_ROUTE)
        else:
            controller.activate_write_once()
    assert controller.phase is WriterPolicyPhase.ABORTED


# --------------------------------------------------------------------- #
# authorize_exact_mission_route's own inline validation
# --------------------------------------------------------------------- #


def test_authorize_rejects_wrong_host():
    controller = _new_controller()
    bad = RouteContract(
        host="evil.example.com",
        route=MISSION_ROUTE,
        method="GET",
        query_fields=frozenset(),
        content_type=None,
        body_fields=frozenset(),
        capability="read",
        operation_type="mission_open",
        workflow=None,
    )
    with pytest.raises(ValueError):
        controller.authorize_exact_mission_route(bad, expected_route=MISSION_ROUTE)
    assert controller.phase is WriterPolicyPhase.SEARCH_READ


def test_authorize_rejects_non_get_method():
    controller = _new_controller()
    bad = RouteContract(
        host=ALLOWED_HOST,
        route=MISSION_ROUTE,
        method="POST",
        query_fields=frozenset(),
        content_type="application/x-www-form-urlencoded",
        body_fields=frozenset(),
        capability="read",
        operation_type="mission_open",
        workflow=None,
    )
    with pytest.raises(ValueError):
        controller.authorize_exact_mission_route(bad, expected_route=MISSION_ROUTE)


def test_authorize_rejects_wrong_capability():
    controller = _new_controller()
    bad = RouteContract(
        host=ALLOWED_HOST,
        route=MISSION_ROUTE,
        method="GET",
        query_fields=frozenset(),
        content_type=None,
        body_fields=frozenset(),
        capability="row_write",
        operation_type="mission_open",
        workflow=None,
    )
    with pytest.raises(ValueError):
        controller.authorize_exact_mission_route(bad, expected_route=MISSION_ROUTE)


def test_authorize_rejects_wrong_operation_type():
    controller = _new_controller()
    bad = RouteContract(
        host=ALLOWED_HOST,
        route=MISSION_ROUTE,
        method="GET",
        query_fields=frozenset(),
        content_type=None,
        body_fields=frozenset(),
        capability="read",
        operation_type="mission_page",
        workflow=None,
    )
    with pytest.raises(ValueError):
        controller.authorize_exact_mission_route(bad, expected_route=MISSION_ROUTE)


def test_authorize_rejects_unexpected_query_fields():
    controller = _new_controller()
    bad = RouteContract(
        host=ALLOWED_HOST,
        route=MISSION_ROUTE,
        method="GET",
        query_fields=frozenset({"workflow"}),
        content_type=None,
        body_fields=frozenset(),
        capability="read",
        operation_type="mission_open",
        workflow=None,
    )
    with pytest.raises(ValueError):
        controller.authorize_exact_mission_route(bad, expected_route=MISSION_ROUTE)


def test_authorize_rejects_route_not_matching_expected_route():
    controller = _new_controller()
    with pytest.raises(ValueError):
        controller.authorize_exact_mission_route(
            MISSION_CONTRACT, expected_route="/SinAuto_MCMA/expertise/gestionExpert/getSinistre/idSinistre/999/rubrique/gestionexpert-index"
        )


def test_authorize_rejects_permanently_blocked_route():
    controller = _new_controller()
    blocked_route = "/SinAuto_MCMA/expertise/gestionexpert/deleteDevisDet"
    bad = RouteContract(
        host=ALLOWED_HOST,
        route=blocked_route,
        method="GET",
        query_fields=frozenset(),
        content_type=None,
        body_fields=frozenset(),
        capability="read",
        operation_type="mission_open",
        workflow=None,
    )
    with pytest.raises(ValueError):
        controller.authorize_exact_mission_route(bad, expected_route=blocked_route)


# --------------------------------------------------------------------- #
# AbortOnlyHandle: structurally narrower than "please don't call the
# other methods" -- the object literally has no other method.
# --------------------------------------------------------------------- #


def test_abort_only_handle_has_exactly_one_public_method():
    controller = _new_controller()
    handle = AbortOnlyHandle(controller)
    public_methods = [name for name in dir(handle) if not name.startswith("_")]
    assert public_methods == ["abort"]


def test_abort_only_handle_abort_calls_controller_abort_deny_all():
    controller = _new_controller()
    handle = AbortOnlyHandle(controller)
    handle.abort()
    assert controller.phase is WriterPolicyPhase.ABORTED
    assert controller.contracts() == ()


# --------------------------------------------------------------------- #
# Every request denied after ABORTED, paired with a positive control
# proving activation genuinely allows the write contract beforehand.
# --------------------------------------------------------------------- #


def test_every_request_denied_after_abort_with_positive_control_before():
    controller = _new_controller()
    controller.authorize_exact_mission_route(MISSION_CONTRACT, expected_route=MISSION_ROUTE)
    controller.activate_write_once()

    async def scenario():
        context = FakeContext()
        await install_phased_portal_guard(context, controller, ALLOWED_HOST)
        pattern, handler = context.route_calls[0]

        request = FakeRequest(
            url=f"http://{ALLOWED_HOST}{WRITE_CONTRACT.route}",
            method="POST",
            headers={"content-type": "application/x-www-form-urlencoded"},
            post_data="IdRubrique=1&MontantHT=10.00&Taxe=2.00&MontantTTC=12.00&TauxVetuste=0.00&MontantVetuste=0.00&TempRowId=tmp-1",
        )
        allowed_route = FakeRoute(request)
        await handler(allowed_route)
        assert allowed_route.continued == 1
        assert allowed_route.aborted == 0

        controller.abort_deny_all()

        denied_route = FakeRoute(request)
        await handler(denied_route)
        assert denied_route.aborted == 1
        assert denied_route.continued == 0

    run_async(scenario())
