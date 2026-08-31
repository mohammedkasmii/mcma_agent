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


def test_public_surface_is_exactly_the_five_operations_plus_close():
    """INC-14 disclosed extension: read_notifications() was added (the
    recovered getAlerte/DataTable contract, read-only, category-scoped) --
    every other operation and close() are unchanged."""
    public = {
        name for name in dir(ReadCapability) if not name.startswith("_") and callable(getattr(ReadCapability, name))
    }
    assert public == {"search", "open", "scrape", "read_rows", "read_notifications", "close"}


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
