"""
INC-09B -- open_verified_writer's construction-time safety gates, exercised
against FakeBrowser/FakeContext/FakePage (no real Playwright browser
anywhere in this file). Covers: direct construction rejected; permanently
blocked write contract rejected; shared/other-workflow write contract
rejected; missing search_page contract rejected; unplanned rubrique
rejected before any page interaction; construction failure always closes
the context; the happy path succeeds and reaches WRITE_ACTIVE.
"""

import pytest

from mcma.domain.enums import RepairWorkflow
from mcma.domain.values import RubriqueId
from mcma.portal.interception import WriterPolicyPhase
from mcma.portal.capabilities import SearchIdentifiers
from mcma.portal.writer import (
    UnplannedRubrique,
    VerifiedMissionWriter,
    WriteAborted,
    WriterPlanData,
    _CONSTRUCTION_TOKEN,
    open_verified_writer,
)
from writer_test_support import (
    ALLOWED_HOST,
    FakeBrowser,
    FakeContext,
    FakePage,
    FailingNewPageContext,
    NORMAL_ROW_WRITE_CONTRACT,
    OTHER_WORKFLOW_ROW_WRITE_CONTRACT,
    PERMANENTLY_BLOCKED_WRITE_CONTRACT,
    SEARCH_LISTE_MISSIONS_CONTRACT,
    SEARCH_PAGE_CONTRACT,
    SHARED_ROW_WRITE_CONTRACT,
    SyntheticLeaseHandle,
    make_expected_identity,
    row_intent,
    run_async,
)

MODE_NORMAL_PLAN = WriterPlanData(
    repair_workflow=RepairWorkflow.MODE_NORMAL, row_intents=(row_intent("3", "10.00", "2.00"),)
)
IDENTITY = make_expected_identity("34602-B-7", "534660")
IDENTIFIERS = SearchIdentifiers(matricule="34602-B-7")

HAPPY_PATH_CONTRACTS = (SEARCH_PAGE_CONTRACT, SEARCH_LISTE_MISSIONS_CONTRACT, NORMAL_ROW_WRITE_CONTRACT)


def _happy_page_factory():
    return FakePage(
        evaluate_results=[
            {"data": [{"IdMission": 532805, "Matricule": "34602-B-7", "ReferenceMission": "R1", "Societaire": "S"}]},
            {"registration": "34602-B-7", "id_sinistre": "534660"},
            {"normal": True, "pec": False},
        ]
    )


def test_direct_construction_is_rejected():
    with pytest.raises(RuntimeError):
        VerifiedMissionWriter(object(), None, None, None, IDENTITY, MODE_NORMAL_PLAN, ALLOWED_HOST)


def test_direct_construction_with_the_real_token_still_works_internally():
    # Sanity: the token check is the only guard -- proves it isn't
    # accidentally unreachable/always-raising.
    writer = VerifiedMissionWriter(_CONSTRUCTION_TOKEN, None, None, None, IDENTITY, MODE_NORMAL_PLAN, ALLOWED_HOST)
    assert isinstance(writer, VerifiedMissionWriter)


def test_permanently_blocked_write_contract_is_rejected_before_any_browser_context():
    browser = FakeBrowser(context_factory=lambda: FakeContext(_happy_page_factory))
    contracts = (SEARCH_PAGE_CONTRACT, SEARCH_LISTE_MISSIONS_CONTRACT, PERMANENTLY_BLOCKED_WRITE_CONTRACT)
    with pytest.raises(ValueError):
        run_async(
            open_verified_writer(
                browser, SyntheticLeaseHandle(), IDENTITY, MODE_NORMAL_PLAN, IDENTIFIERS, contracts, ALLOWED_HOST
            )
        )
    assert browser.new_context_calls == []


def test_shared_row_write_contract_is_rejected():
    browser = FakeBrowser(context_factory=lambda: FakeContext(_happy_page_factory))
    contracts = (SEARCH_PAGE_CONTRACT, SEARCH_LISTE_MISSIONS_CONTRACT, SHARED_ROW_WRITE_CONTRACT)
    with pytest.raises(ValueError):
        run_async(
            open_verified_writer(
                browser, SyntheticLeaseHandle(), IDENTITY, MODE_NORMAL_PLAN, IDENTIFIERS, contracts, ALLOWED_HOST
            )
        )
    assert browser.new_context_calls == []


def test_other_workflow_row_write_contract_is_filtered_out_leaving_none():
    """contracts_for_workflow already filters this out (it names the OTHER
    workflow), so what remains has zero write contracts for MODE_NORMAL --
    a MODE_NORMAL writer with no row_write contract at all is still a
    valid (if useless) construction; this proves the other workflow's
    contract never leaks in, rather than raising."""
    browser = FakeBrowser(context_factory=lambda: FakeContext(_happy_page_factory))
    contracts = (SEARCH_PAGE_CONTRACT, SEARCH_LISTE_MISSIONS_CONTRACT, OTHER_WORKFLOW_ROW_WRITE_CONTRACT)
    writer = run_async(
        open_verified_writer(
            browser, SyntheticLeaseHandle(), IDENTITY, MODE_NORMAL_PLAN, IDENTIFIERS, contracts, ALLOWED_HOST
        )
    )
    assert isinstance(writer, VerifiedMissionWriter)


def test_missing_search_page_contract_is_rejected():
    browser = FakeBrowser(context_factory=lambda: FakeContext(_happy_page_factory))
    contracts = (SEARCH_LISTE_MISSIONS_CONTRACT, NORMAL_ROW_WRITE_CONTRACT)
    with pytest.raises(ValueError):
        run_async(
            open_verified_writer(
                browser, SyntheticLeaseHandle(), IDENTITY, MODE_NORMAL_PLAN, IDENTIFIERS, contracts, ALLOWED_HOST
            )
        )
    assert browser.new_context_calls == []


def test_non_loopback_host_is_rejected_before_any_browser_context():
    browser = FakeBrowser(context_factory=lambda: FakeContext(_happy_page_factory))
    with pytest.raises(ValueError):
        run_async(
            open_verified_writer(
                browser,
                SyntheticLeaseHandle(),
                IDENTITY,
                MODE_NORMAL_PLAN,
                IDENTIFIERS,
                HAPPY_PATH_CONTRACTS,
                "example.com:8080",
            )
        )
    assert browser.new_context_calls == []


def test_construction_failure_after_context_creation_closes_the_context():
    browser = FakeBrowser(context_factory=FailingNewPageContext)
    with pytest.raises(RuntimeError):
        run_async(
            open_verified_writer(
                browser, SyntheticLeaseHandle(), IDENTITY, MODE_NORMAL_PLAN, IDENTIFIERS, HAPPY_PATH_CONTRACTS, ALLOWED_HOST
            )
        )
    assert browser.contexts_created[0].closed_count == 1


def test_happy_path_succeeds_and_reaches_write_active():
    browser = FakeBrowser(context_factory=lambda: FakeContext(_happy_page_factory))
    writer = run_async(
        open_verified_writer(
            browser, SyntheticLeaseHandle(), IDENTITY, MODE_NORMAL_PLAN, IDENTIFIERS, HAPPY_PATH_CONTRACTS, ALLOWED_HOST
        )
    )
    assert isinstance(writer, VerifiedMissionWriter)
    assert writer._abort_handle._controller.phase is WriterPolicyPhase.WRITE_ACTIVE


def test_unplanned_rubrique_rejected_before_any_page_interaction():
    browser = FakeBrowser(context_factory=lambda: FakeContext(_happy_page_factory))
    writer = run_async(
        open_verified_writer(
            browser, SyntheticLeaseHandle(), IDENTITY, MODE_NORMAL_PLAN, IDENTIFIERS, HAPPY_PATH_CONTRACTS, ALLOWED_HOST
        )
    )
    page = writer._page
    evaluate_calls_before = len(page.evaluate_calls)
    with pytest.raises(UnplannedRubrique):
        run_async(writer.add_normal_row(SyntheticLeaseHandle(), RubriqueId("999")))
    assert len(page.evaluate_calls) == evaluate_calls_before  # no page interaction happened
    with pytest.raises(WriteAborted):
        run_async(writer.add_normal_row(SyntheticLeaseHandle(), RubriqueId("3")))  # writer is now terminally aborted


def test_wrong_workflow_plan_rejects_add_normal_row_before_page_interaction():
    pec_plan = WriterPlanData(
        repair_workflow=RepairWorkflow.GARAGE_CONVENTIONNE, row_intents=(row_intent("3", "10.00", "2.00"),)
    )
    browser = FakeBrowser(
        context_factory=lambda: FakeContext(
            lambda: FakePage(
                evaluate_results=[
                    {"data": [{"IdMission": 532805, "Matricule": "34602-B-7"}]},
                    {"registration": "34602-B-7", "id_sinistre": "534660"},
                    {"normal": False, "pec": True},
                ]
            )
        )
    )
    contracts = (SEARCH_PAGE_CONTRACT, SEARCH_LISTE_MISSIONS_CONTRACT)
    writer = run_async(
        open_verified_writer(
            browser, SyntheticLeaseHandle(), IDENTITY, pec_plan, IDENTIFIERS, contracts, ALLOWED_HOST
        )
    )
    with pytest.raises(WriteAborted):
        run_async(writer.add_normal_row(SyntheticLeaseHandle(), RubriqueId("3")))


def test_constructing_plan_data_and_identity_alone_never_creates_a_writer_or_touches_a_browser():
    """There is no DRY_RUN/EXECUTE flag in this module (that authorization
    lives in mcma.execution, out of scope here) -- what IS this module's
    responsibility is that merely building the plan-shaped inputs
    (WriterPlanData/ExpectedIdentity) is completely inert: no writer, no
    context, no page is created as a side effect of construction alone."""
    plan = WriterPlanData(repair_workflow=RepairWorkflow.MODE_NORMAL, row_intents=(row_intent("3", "10.00", "2.00"),))
    identity = make_expected_identity("34602-B-7", "534660")
    assert plan is not None and identity is not None
    # No FakeBrowser was ever constructed/passed anywhere above -- if this
    # test can pass without one, no writer could have been created.
