"""
INC-08 amendment #3 -- ReadCapability's four operations must not become
generic escape hatches: typed identifiers, capability-minted candidates
only, fixed approved-field selectors, RepairWorkflow-typed row reads, fixed
internal scripts with caller data passed only as serialized arguments.
"""

import inspect

import pytest

from capabilities_test_support import (
    ALLOWED_HOST,
    AUTH_LOGIN_CONTRACT,
    FailingNewPageContext,
    FakeBrowser,
    FakeContext,
    FakeRequest,
    FakeRoute,
    READ_LIST_MISSIONS_CONTRACT,
    READ_NORMAL_ROWS_CONTRACT,
    READ_PEC_ROWS_CONTRACT,
    READ_SEARCH_PAGE_CONTRACT,
    ROGUE_ROW_WRITE_CONTRACT,
    SyntheticLeaseHandle,
    run_async,
)
from mcma.domain.enums import RepairWorkflow
from mcma.portal.capabilities import (
    ApprovedField,
    Candidate,
    ReadCapability,
    SearchIdentifiers,
    open_reader,
)
from mcma.portal.contracts import RouteContract
from mcma.portal.interception import (
    PolicyPhaseError,
    ReadOnlyMissionPolicyController,
    install_phased_portal_guard,
)

ALL_CONTRACTS = (
    READ_LIST_MISSIONS_CONTRACT,
    READ_NORMAL_ROWS_CONTRACT,
    READ_PEC_ROWS_CONTRACT,
    READ_SEARCH_PAGE_CONTRACT,
)


def _open(browser=None, lease=None, contracts=ALL_CONTRACTS):
    browser = browser or FakeBrowser()
    lease = lease or SyntheticLeaseHandle()
    return browser, run_async(open_reader(browser, lease, contracts, ALLOWED_HOST))


# --------------------------------------------------------------------- #
# Contract-scope enforcement
# --------------------------------------------------------------------- #


def test_open_reader_rejects_non_read_contract():
    browser = FakeBrowser()
    with pytest.raises(ValueError):
        run_async(open_reader(browser, SyntheticLeaseHandle(), (AUTH_LOGIN_CONTRACT,), ALLOWED_HOST))
    assert browser.new_context_calls == []


def test_open_reader_rejects_row_write_contract():
    browser = FakeBrowser()
    with pytest.raises(ValueError):
        run_async(
            open_reader(browser, SyntheticLeaseHandle(), (ROGUE_ROW_WRITE_CONTRACT,), ALLOWED_HOST)
        )
    assert browser.new_context_calls == []


def test_open_reader_closes_context_when_new_page_fails():
    browser = FakeBrowser(context_factory=FailingNewPageContext)
    with pytest.raises(RuntimeError):
        run_async(open_reader(browser, SyntheticLeaseHandle(), ALL_CONTRACTS, ALLOWED_HOST))
    assert browser.contexts_created[0].closed_count == 1


def test_open_reader_requires_exactly_one_search_page_contract():
    browser = FakeBrowser()
    contracts_without_search_page = (READ_LIST_MISSIONS_CONTRACT, READ_NORMAL_ROWS_CONTRACT)
    with pytest.raises(ValueError):
        run_async(
            open_reader(browser, SyntheticLeaseHandle(), contracts_without_search_page, ALLOWED_HOST)
        )
    assert browser.new_context_calls == []


def test_open_reader_rejects_multiple_search_page_contracts():
    browser = FakeBrowser()
    duplicated = ALL_CONTRACTS + (READ_SEARCH_PAGE_CONTRACT,)
    with pytest.raises(ValueError):
        run_async(open_reader(browser, SyntheticLeaseHandle(), duplicated, ALLOWED_HOST))
    assert browser.new_context_calls == []


def test_open_reader_navigates_to_the_search_page_before_returning_the_capability():
    browser, reader = _open()
    page = browser.contexts_created[0].pages_created[0]
    # The navigation to a same-origin page must happen BEFORE any fetch-based
    # operation is available -- this is the actual fix for a page that would
    # otherwise stay at about:blank (opaque/null origin), where a fetch() to
    # any host is cross-origin and rejected by the browser's own CORS
    # enforcement regardless of the portal interception policy.
    assert page.goto_calls == [f"http://{ALLOWED_HOST}{READ_SEARCH_PAGE_CONTRACT.route}"]
    assert page.evaluate_calls == []
    run_async(reader.close())


# --------------------------------------------------------------------- #
# search(): typed identifiers only
# --------------------------------------------------------------------- #


def test_search_rejects_raw_dict():
    _, reader = _open()
    with pytest.raises(TypeError):
        run_async(reader.search({"Matricule": "34602-B-7"}))


def test_search_identifiers_requires_at_least_one_field():
    with pytest.raises(ValueError):
        SearchIdentifiers()


def test_search_returns_candidates_and_only_sends_fixed_script_with_serialized_data():
    browser, reader = _open()
    page = browser.contexts_created[0].pages_created[0]
    page._evaluate_results = [
        {"data": [{"IdMission": 532805, "Matricule": "34602-B-7", "ReferenceMission": "R1", "Societaire": "ACME"}]}
    ]
    injection_attempt = "'); alert(document.cookie); //"
    candidates = run_async(reader.search(SearchIdentifiers(matricule=injection_attempt)))
    assert len(candidates) == 1
    assert isinstance(candidates[0], Candidate)
    assert candidates[0].id_mission == 532805

    script, arg = page.evaluate_calls[0]
    assert injection_attempt not in script  # never interpolated into the script text
    assert injection_attempt in arg[1]["Matricule"]  # only ever passed as serialized data


# --------------------------------------------------------------------- #
# open(): only this capability's own candidates; no caller-supplied URL
# --------------------------------------------------------------------- #


def test_open_rejects_a_plain_string_url():
    _, reader = _open()
    with pytest.raises(TypeError):
        run_async(reader.open("http://evil.example.com/expertise/gestiongarage/garageModifierValDevis"))


def test_open_rejects_a_forged_candidate_with_wrong_owner_token():
    _, reader = _open()
    forged = Candidate(
        id_mission=1, matricule="X", reference_mission="Y", societaire="Z", owner_token=object()
    )
    with pytest.raises(ValueError):
        run_async(reader.open(forged))


def test_open_navigates_using_only_id_mission_never_a_route_field():
    browser, reader = _open()
    page = browser.contexts_created[0].pages_created[0]
    page._evaluate_results = [{"data": [{"IdMission": 42, "Matricule": "X", "ReferenceMission": "Y", "Societaire": "Z"}]}]
    (candidate,) = run_async(reader.search(SearchIdentifiers(matricule="X")))
    run_async(reader.open(candidate))
    # goto_calls[0] is open_reader's own initial navigation to the reviewed
    # search-page contract; open() appends the mission deep link after it.
    assert page.goto_calls[1:] == [
        f"http://{ALLOWED_HOST}/SinAuto_MCMA/expertise/gestionExpert/getSinistre/idSinistre/42/rubrique/gestionexpert-index"
    ]


def test_open_percent_escapes_a_malicious_id_mission_instead_of_traversing():
    browser, reader = _open()
    page = browser.contexts_created[0].pages_created[0]
    candidate = Candidate(
        id_mission="../../gestiongarage/garageModifierValDevis",
        matricule="X",
        reference_mission="Y",
        societaire="Z",
        owner_token=reader._capability_token,
    )
    run_async(reader.open(candidate))
    url = page.goto_calls[-1]
    # The escaped id segment must not contain a literal, unescaped "/" --
    # otherwise it would extend the path instead of staying one segment.
    id_segment = url.split("idSinistre/", 1)[1].split("/rubrique")[0]
    assert "/" not in id_segment


def test_candidate_has_no_route_or_url_attribute():
    candidate = Candidate(id_mission=1, matricule="X", reference_mission="Y", societaire="Z", owner_token=object())
    assert not hasattr(candidate, "route")
    assert not hasattr(candidate, "url")
    assert not hasattr(candidate, "raw")


def test_candidate_construction_rejects_arbitrary_extra_fields():
    with pytest.raises(TypeError):
        Candidate(
            id_mission=1,
            matricule="X",
            reference_mission="Y",
            societaire="Z",
            owner_token=object(),
            route="http://evil.example.com/x",
        )


# --------------------------------------------------------------------- #
# scrape(): fixed approved fields only, never caller-supplied selectors
# --------------------------------------------------------------------- #


def test_scrape_rejects_raw_selector_dict():
    _, reader = _open()
    with pytest.raises(TypeError):
        run_async(reader.scrape({"matricule": "#MatriculeVeh"}))


def test_scrape_rejects_a_plain_string_selector_list():
    _, reader = _open()
    with pytest.raises(TypeError):
        run_async(reader.scrape(["#MatriculeVeh"]))


def test_scrape_uses_only_the_fixed_internal_script_and_selector_map():
    browser, reader = _open()
    page = browser.contexts_created[0].pages_created[0]
    page._evaluate_results = [{"MATRICULE_VEH": "34602-B-7"}]
    result = run_async(reader.scrape((ApprovedField.MATRICULE_VEH,)))
    assert result == {"MATRICULE_VEH": "34602-B-7"}
    script, arg = page.evaluate_calls[0]
    assert "document.querySelector" in script
    assert arg == [("MATRICULE_VEH", "#MatriculeVeh")]


# --------------------------------------------------------------------- #
# read_rows(): RepairWorkflow only, never an arbitrary string
# --------------------------------------------------------------------- #


def test_read_rows_rejects_arbitrary_string_workflow():
    _, reader = _open()
    with pytest.raises(TypeError):
        run_async(reader.read_rows("MODE_NORMAL"))


def test_read_rows_normal_and_pec_use_separate_fixed_routes():
    browser, reader = _open()
    page = browser.contexts_created[0].pages_created[0]
    page._evaluate_results = [{"data": []}, {"data": []}]
    run_async(reader.read_rows(RepairWorkflow.MODE_NORMAL))
    run_async(reader.read_rows(RepairWorkflow.GARAGE_CONVENTIONNE))
    normal_url = page.evaluate_calls[0][1][0]
    pec_url = page.evaluate_calls[1][1][0]
    assert normal_url.endswith("/listeRapportDefDet")
    assert pec_url.endswith("/listeDevisDet")
    assert normal_url != pec_url


# --------------------------------------------------------------------- #
# observe_identity(): the same fixed script mcma.portal.identity already
# uses for EXECUTE's write-side gate, now reachable read-only too
# --------------------------------------------------------------------- #


def test_observe_identity_uses_the_fixed_script_and_returns_a_typed_result():
    from mcma.domain.values import IdSinistre, RegistrationPlate
    from mcma.portal.identity import ObservedIdentity

    browser, reader = _open()
    page = browser.contexts_created[0].pages_created[0]
    page._evaluate_results = [{"registration": "34602-B-7", "id_sinistre": "534660"}]
    observed = run_async(reader.observe_identity())
    assert observed == ObservedIdentity(
        registration=RegistrationPlate("34602-B-7"),
        insurer_reference=None,
        id_sinistre=IdSinistre("534660"),
    )
    script, arg = page.evaluate_calls[0]
    assert "MatriculeVeh" in script and "IdSinistre__I" in script
    assert arg is None  # no caller-supplied argument -- the script is fully fixed


def test_observe_identity_fails_after_close_without_touching_the_page():
    browser, reader = _open()
    page = browser.contexts_created[0].pages_created[0]
    run_async(reader.close())
    with pytest.raises(RuntimeError):
        run_async(reader.observe_identity())
    assert page.evaluate_calls == []


# --------------------------------------------------------------------- #
# observe_session_state(): non-strict by construction -- an evaluation
# exception maps to INDETERMINATE, never propagates. This is the exact
# behavior mcma.portal.workstation_sessions relies on being UNCHANGED
# while it separately calls the same underlying helper in strict mode.
# --------------------------------------------------------------------- #


def test_observe_session_state_maps_evaluation_exception_to_indeterminate():
    browser, reader = _open()
    page = browser.contexts_created[0].pages_created[0]
    page._evaluate_results = [RuntimeError("boom")]
    state = run_async(reader.observe_session_state())
    assert state == "INDETERMINATE"


def test_observe_session_state_maps_authenticated_marker():
    browser, reader = _open()
    page = browser.contexts_created[0].pages_created[0]
    page._evaluate_results = [{"logged_in": True, "logged_out": False}]
    state = run_async(reader.observe_session_state())
    assert state == "AUTHENTICATED"


def test_observe_session_state_maps_logged_out_marker():
    browser, reader = _open()
    page = browser.contexts_created[0].pages_created[0]
    page._evaluate_results = [{"logged_in": False, "logged_out": True}]
    state = run_async(reader.observe_session_state())
    assert state == "LOGGED_OUT"


# --------------------------------------------------------------------- #
# Lifecycle: fail after close without touching the page; idempotent close
# --------------------------------------------------------------------- #


def test_methods_fail_after_close_without_touching_the_page():
    browser, reader = _open()
    page = browser.contexts_created[0].pages_created[0]
    run_async(reader.close())
    with pytest.raises(RuntimeError):
        run_async(reader.read_rows(RepairWorkflow.MODE_NORMAL))
    assert page.evaluate_calls == []


def test_close_is_idempotent():
    browser, reader = _open()
    run_async(reader.close())
    run_async(reader.close())
    assert browser.contexts_created[0].closed_count == 1


# --------------------------------------------------------------------- #
# Public surface: no upgrade-to-writer path, no raw context/page
# --------------------------------------------------------------------- #


def test_public_surface_is_exactly_the_eight_operations_plus_close():
    """INC-14 disclosed extension: read_notifications() was added (the
    recovered getAlerte/DataTable contract, read-only, category-scoped).
    Pilot-integration correction (section 3): observe_identity() was added
    -- the same fixed-script scraping mcma.portal.identity already
    provides for EXECUTE's write-side identity gate, now also reachable
    read-only for the real DRY_RUN job runner.

    Phase B disclosed extension: discover_notification_categories() was
    added. This widens a deliberately closed surface, so the reasoning is
    recorded rather than the list quietly edited.

    No reviewed fixed list of alert category codes exists anywhere in this
    repository -- the categories table ships empty -- and the baseline
    read the active codes from the portal's own notification surface
    (PORTAL_CONTRACT.md §7). Polling therefore cannot happen without
    discovery. The operation stays inside the same constraints as every
    other one here: it is read-only, runs one FIXED internal script,
    accepts no caller input, and returns validated CODES ONLY. The DOM's
    hrefs never leave the page, so nothing portal-supplied can become a
    route this capability will fetch, and a discovered code still cannot
    be read without a reviewed RouteContract installed for that exact
    category on a different context. Every other operation and close() are
    unchanged."""
    public = {
        name for name in dir(ReadCapability) if not name.startswith("_") and callable(getattr(ReadCapability, name))
    }
    assert public == {
        "search",
        "open",
        "scrape",
        "read_rows",
        "read_notifications",
        "discover_notification_categories",
        "observe_session_state",
        "observe_identity",
        "close",
    }


def test_no_page_context_or_generic_request_exposed():
    public_instance_attrs = {n for n in dir(ReadCapability) if not n.startswith("_")}
    for forbidden in ("page", "context", "evaluate", "request", "write", "writer"):
        assert forbidden not in public_instance_attrs


def test_read_capability_source_never_references_write_or_final_endpoints():
    source = inspect.getsource(ReadCapability)
    forbidden = (
        "createRapportDefDet",
        "updateDevisDet",
        "garageModifierValDevis",
        "validerDevis",
        "expertCloturerMission",
        "cloturerMission",
        "enregistrerMission",
        "ajouterDocument",
        "deleteDocument",
        "cloturerTraitement",
        "deleteDevisDet",
    )
    for token in forbidden:
        assert token not in source, token


# --------------------------------------------------------------------- #
# Phase 1C-B release-blocker correction: dynamic_mission_authorization --
# a real (non-mock-fixture) mission id, authorized at runtime from a
# validated search Candidate, with no wildcard route and no client/dossier
# value ever used directly as a URL. Contracts deliberately carry ONLY the
# search-page/search-request routes -- no mission_page/mission_open
# contract exists anywhere in this initial set, since none could: the
# mission id is not known until search() returns.
# --------------------------------------------------------------------- #

IDENTITY_READ_CONTRACTS = (READ_SEARCH_PAGE_CONTRACT, READ_LIST_MISSIONS_CONTRACT)

MISSION_ID = 987654  # a non-fixture id -- neither mock mission (612001/532805) nor MISSION_CONTRACT's 532805
MISSION_ROUTE = f"/SinAuto_MCMA/expertise/gestionExpert/getSinistre/idSinistre/{MISSION_ID}/rubrique/gestionexpert-index"
OTHER_MISSION_ROUTE = "/SinAuto_MCMA/expertise/gestionExpert/getSinistre/idSinistre/111111/rubrique/gestionexpert-index"


def _mission_contract(route: str) -> RouteContract:
    return RouteContract(
        host=ALLOWED_HOST, route=route, method="GET", query_fields=frozenset(), content_type=None,
        body_fields=frozenset(), capability="read", operation_type="mission_open", workflow=None,
    )


def _open_dynamic(browser=None, lease=None, contracts=IDENTITY_READ_CONTRACTS):
    browser = browser or FakeBrowser()
    lease = lease or SyntheticLeaseHandle()
    reader = run_async(
        open_reader(browser, lease, contracts, ALLOWED_HOST, dynamic_mission_authorization=True)
    )
    return browser, reader


def _found_candidate(reader, page, id_mission) -> Candidate:
    page._evaluate_results = [
        {"data": [{"IdMission": id_mission, "Matricule": "X", "ReferenceMission": "Y", "Societaire": "Z"}]}
    ]
    (candidate,) = run_async(reader.search(SearchIdentifiers(matricule="X")))
    return candidate


def test_open_reader_with_no_dynamic_authorization_is_completely_unchanged():
    """The default (dynamic_mission_authorization=False, unspecified) --
    every OTHER caller of open_reader (notification reading, etc.) keeps
    today's exact static-contract behavior."""
    browser, reader = _open(contracts=ALL_CONTRACTS)
    assert reader._mission_policy_controller is None


def test_dynamic_mission_authorization_permits_the_exact_searched_route():
    browser, reader = _open_dynamic()
    page = browser.contexts_created[0].pages_created[0]
    candidate = _found_candidate(reader, page, MISSION_ID)
    run_async(reader.open(candidate))
    assert page.goto_calls[-1] == f"http://{ALLOWED_HOST}{MISSION_ROUTE}"


def test_dynamic_mission_authorization_refuses_a_second_open_for_a_different_mission():
    """SEARCH_READ -> MISSION_READ is usable at most once per session --
    a second candidate (a genuinely different mission id) is refused, not
    silently re-authorized."""
    browser, reader = _open_dynamic()
    page = browser.contexts_created[0].pages_created[0]
    first = _found_candidate(reader, page, MISSION_ID)
    run_async(reader.open(first))
    other = Candidate(id_mission=111111, matricule="X", reference_mission="Y", societaire="Z", owner_token=reader._capability_token)
    with pytest.raises(PolicyPhaseError):
        run_async(reader.open(other))


@pytest.mark.parametrize("bad_id", ["987654", "987654; DROP TABLE", "../../gestiongarage/garageModifierValDevis", None, 1.5, True])
def test_dynamic_mission_authorization_refuses_a_forged_or_malformed_mission_id(bad_id):
    browser, reader = _open_dynamic()
    forged = Candidate(id_mission=bad_id, matricule="X", reference_mission="Y", societaire="Z", owner_token=reader._capability_token)
    with pytest.raises(ValueError):
        run_async(reader.open(forged))


@pytest.mark.parametrize("bad_id", [-1, 0, 10 ** 12])
def test_dynamic_mission_authorization_refuses_a_negative_zero_or_unbounded_mission_id(bad_id):
    browser, reader = _open_dynamic()
    candidate = Candidate(id_mission=bad_id, matricule="X", reference_mission="Y", societaire="Z", owner_token=reader._capability_token)
    with pytest.raises(ValueError):
        run_async(reader.open(candidate))


def test_dynamic_mission_authorization_still_rejects_the_wrong_owner_token():
    browser, reader = _open_dynamic()
    forged = Candidate(id_mission=MISSION_ID, matricule="X", reference_mission="Y", societaire="Z", owner_token=object())
    with pytest.raises(ValueError):
        run_async(reader.open(forged))


def test_dynamic_mission_authorization_still_rejects_a_plain_string_url():
    browser, reader = _open_dynamic()
    with pytest.raises(TypeError):
        run_async(reader.open("http://evil.example.com/expertise/gestiongarage/garageModifierValDevis"))


def test_only_read_operations_remain_reachable_from_the_read_only_controller():
    """No write-shaped method exists anywhere on ReadOnlyMissionPolicyController
    -- structurally, not merely by convention -- and ReadCapability itself
    still exposes none either."""
    controller_methods = {name for name in dir(ReadOnlyMissionPolicyController) if not name.startswith("_")}
    assert controller_methods == {"phase", "contracts", "authorize_exact_mission_route"}
    assert not hasattr(ReadOnlyMissionPolicyController, "activate_write_once")
    reader_methods = {name for name in dir(ReadCapability) if not name.startswith("_")}
    assert reader_methods == {"search", "open", "scrape", "observe_identity", "discover_notification_categories", "observe_session_state", "read_notifications", "read_rows", "close"}


def test_guard_permits_exactly_the_authorized_route_and_denies_a_different_one():
    """The actual interception decision (mcma.portal.interception.
    evaluate_request, via the installed phased handler) -- not just the
    controller's own bookkeeping."""
    controller = ReadOnlyMissionPolicyController(IDENTITY_READ_CONTRACTS, ALLOWED_HOST)
    controller.authorize_exact_mission_route(_mission_contract(MISSION_ROUTE), expected_route=MISSION_ROUTE)

    async def scenario():
        context = FakeContext()
        await install_phased_portal_guard(context, controller, ALLOWED_HOST)
        _pattern, handler = context.route_calls[0]

        allowed = FakeRoute(FakeRequest(url=f"http://{ALLOWED_HOST}{MISSION_ROUTE}", method="GET"))
        await handler(allowed)
        assert allowed.continued == 1 and allowed.aborted == 0

        denied = FakeRoute(FakeRequest(url=f"http://{ALLOWED_HOST}{OTHER_MISSION_ROUTE}", method="GET"))
        await handler(denied)
        assert denied.aborted == 1 and denied.continued == 0

    run_async(scenario())


def test_guard_refuses_authorizing_a_second_mission_route_entirely():
    controller = ReadOnlyMissionPolicyController(IDENTITY_READ_CONTRACTS, ALLOWED_HOST)
    controller.authorize_exact_mission_route(_mission_contract(MISSION_ROUTE), expected_route=MISSION_ROUTE)
    with pytest.raises(PolicyPhaseError):
        controller.authorize_exact_mission_route(_mission_contract(OTHER_MISSION_ROUTE), expected_route=OTHER_MISSION_ROUTE)


def test_guard_refuses_a_foreign_host_contract():
    controller = ReadOnlyMissionPolicyController(IDENTITY_READ_CONTRACTS, ALLOWED_HOST)
    forged = RouteContract(
        host="evil.example.com", route=MISSION_ROUTE, method="GET", query_fields=frozenset(),
        content_type=None, body_fields=frozenset(), capability="read", operation_type="mission_open", workflow=None,
    )
    with pytest.raises(ValueError):
        controller.authorize_exact_mission_route(forged, expected_route=MISSION_ROUTE)


def test_guard_refuses_a_write_shaped_contract():
    controller = ReadOnlyMissionPolicyController(IDENTITY_READ_CONTRACTS, ALLOWED_HOST)
    forged = RouteContract(
        host=ALLOWED_HOST, route=MISSION_ROUTE, method="POST", query_fields=frozenset(),
        content_type="application/x-www-form-urlencoded", body_fields=frozenset({"x"}),
        capability="row_write", operation_type="add_row", workflow=None,
    )
    with pytest.raises(ValueError):
        controller.authorize_exact_mission_route(forged, expected_route=MISSION_ROUTE)


def test_guard_refuses_a_permanently_blocked_route():
    blocked_route = "/SinAuto_MCMA/expertise/gestiongarage/garageModifierValDevis"
    controller = ReadOnlyMissionPolicyController(IDENTITY_READ_CONTRACTS, ALLOWED_HOST)
    forged = RouteContract(
        host=ALLOWED_HOST, route=blocked_route, method="GET", query_fields=frozenset(),
        content_type=None, body_fields=frozenset(), capability="read", operation_type="mission_open", workflow=None,
    )
    with pytest.raises(ValueError):
        controller.authorize_exact_mission_route(forged, expected_route=blocked_route)


def test_guard_refuses_a_mismatched_route_field():
    """expected_route (computed by the caller from the SAME validated
    integer) must match the contract's own route exactly -- a contract for
    a DIFFERENT route than what was actually validated is refused."""
    controller = ReadOnlyMissionPolicyController(IDENTITY_READ_CONTRACTS, ALLOWED_HOST)
    with pytest.raises(ValueError):
        controller.authorize_exact_mission_route(_mission_contract(MISSION_ROUTE), expected_route=OTHER_MISSION_ROUTE)
