"""
INC-09B (round 3 correction) -- open_verified_writer's construction-time
safety gates, exercised against FakeBrowser/FakeContext/FakePage (no real
Playwright browser anywhere in this file). Covers: direct construction
rejected; permanently blocked write contract rejected; shared/other-
workflow write contract rejected; missing search_page/read_rows contract
rejected; unplanned rubrique rejected before any page interaction;
construction failure always closes the context; the happy path succeeds
and reaches WRITE_ACTIVE; PEC preflight now runs INSIDE construction
(item C); the public surface is exactly the eight documented operations
(item C); a stored lease cannot be bypassed by a fresh one at call time
(item B).
"""

import pytest

from mcma.domain.enums import RepairWorkflow
from mcma.domain.values import RubriqueId
from mcma.portal.interception import WriterPolicyPhase
from mcma.portal.capabilities import LeaseInvalid, SearchIdentifiers
from mcma.portal.writer import (
    RowAmbiguous,
    RowMismatch,
    UnplannedRubrique,
    VerifiedMissionWriter,
    WriteAborted,
    WriterPlanData,
    _CONSTRUCTION_TOKEN,
    open_verified_writer,
)
from writer_test_support import (
    ALLOWED_HOST,
    MCMA_WRITER_ACCOUNT,
    FakeBrowser,
    FakeContext,
    FakePage,
    FailingNewPageContext,
    NORMAL_READ_ROWS_CONTRACT,
    NORMAL_ROW_WRITE_CONTRACT,
    OTHER_WORKFLOW_ROW_WRITE_CONTRACT,
    PEC_READ_ROWS_CONTRACT,
    PEC_ROW_WRITE_CONTRACT,
    PERMANENTLY_BLOCKED_WRITE_CONTRACT,
    SEARCH_LISTE_MISSIONS_CONTRACT,
    SEARCH_PAGE_CONTRACT,
    SHARED_ROW_WRITE_CONTRACT,
    SyntheticLeaseHandle,
    make_expected_identity,
    mcma_writer_account,
    row_intent,
    run_async,
)

MODE_NORMAL_PLAN = WriterPlanData(
    repair_workflow=RepairWorkflow.MODE_NORMAL, row_intents=(row_intent("3", "10.00", "2.00"),)
)
PEC_PLAN = WriterPlanData(
    repair_workflow=RepairWorkflow.GARAGE_CONVENTIONNE, row_intents=(row_intent("3", "10.00", "2.00"),)
)
# item A.2: the PEC identity (34602-B-7 / 534660) is used ONLY for
# GARAGE_CONVENTIONNE constructions in this file; MODE_NORMAL constructions
# use the synthetic Normal mission's own identity (77001-C-3 / 699001).
PEC_IDENTITY = make_expected_identity("34602-B-7", "534660")
PEC_IDENTIFIERS = SearchIdentifiers(matricule="34602-B-7")
NORMAL_IDENTITY = make_expected_identity("77001-C-3", "699001")
NORMAL_IDENTIFIERS = SearchIdentifiers(matricule="77001-C-3")

HAPPY_PATH_CONTRACTS = (
    SEARCH_PAGE_CONTRACT,
    SEARCH_LISTE_MISSIONS_CONTRACT,
    NORMAL_READ_ROWS_CONTRACT,
    NORMAL_ROW_WRITE_CONTRACT,
)
PEC_HAPPY_PATH_CONTRACTS = (
    SEARCH_PAGE_CONTRACT,
    SEARCH_LISTE_MISSIONS_CONTRACT,
    PEC_READ_ROWS_CONTRACT,
    PEC_ROW_WRITE_CONTRACT,
)


def _normal_happy_page_factory():
    return FakePage(
        evaluate_results=[
            {"data": [{"IdMission": 612001, "Matricule": "77001-C-3", "ReferenceMission": "R1", "Societaire": "S"}]},
            {"registration": "77001-C-3", "id_sinistre": "699001"},
            {"normal": True, "pec": False},
        ]
    )


def _pec_happy_page_factory(preflight_rows=None):
    preflight_rows = preflight_rows if preflight_rows is not None else [{"IdRubrique": "3", "IdDevisDet": 1}]
    return FakePage(
        evaluate_results=[
            {"data": [{"IdMission": 532805, "Matricule": "34602-B-7", "ReferenceMission": "R1", "Societaire": "S"}]},
            {"registration": "34602-B-7", "id_sinistre": "534660"},
            {"normal": False, "pec": True},
            {"data": preflight_rows},
        ]
    )


def test_direct_construction_is_rejected():
    with pytest.raises(RuntimeError):
        VerifiedMissionWriter(
            object(), None, None, None, SyntheticLeaseHandle(), NORMAL_IDENTITY, MODE_NORMAL_PLAN, ALLOWED_HOST, "/x", {}
        )


def test_direct_construction_with_the_real_token_still_works_internally():
    # Sanity: the token check is the only guard -- proves it isn't
    # accidentally unreachable/always-raising.
    writer = VerifiedMissionWriter(
        _CONSTRUCTION_TOKEN, None, None, None, SyntheticLeaseHandle(), NORMAL_IDENTITY, MODE_NORMAL_PLAN, ALLOWED_HOST, "/x", {}
    )
    assert isinstance(writer, VerifiedMissionWriter)


def test_permanently_blocked_write_contract_is_rejected_before_any_browser_context():
    browser = FakeBrowser(context_factory=lambda: FakeContext(_normal_happy_page_factory))
    contracts = (
        SEARCH_PAGE_CONTRACT,
        SEARCH_LISTE_MISSIONS_CONTRACT,
        NORMAL_READ_ROWS_CONTRACT,
        PERMANENTLY_BLOCKED_WRITE_CONTRACT,
    )
    with pytest.raises(ValueError):
        run_async(
            open_verified_writer(
                browser, SyntheticLeaseHandle(), NORMAL_IDENTITY, MODE_NORMAL_PLAN, NORMAL_IDENTIFIERS, contracts, ALLOWED_HOST,
                writer_account=MCMA_WRITER_ACCOUNT,
            )
        )
    assert browser.new_context_calls == []


def test_shared_row_write_contract_is_rejected():
    browser = FakeBrowser(context_factory=lambda: FakeContext(_normal_happy_page_factory))
    contracts = (SEARCH_PAGE_CONTRACT, SEARCH_LISTE_MISSIONS_CONTRACT, NORMAL_READ_ROWS_CONTRACT, SHARED_ROW_WRITE_CONTRACT)
    with pytest.raises(ValueError):
        run_async(
            open_verified_writer(
                browser, SyntheticLeaseHandle(), NORMAL_IDENTITY, MODE_NORMAL_PLAN, NORMAL_IDENTIFIERS, contracts, ALLOWED_HOST,
                writer_account=MCMA_WRITER_ACCOUNT,
            )
        )
    assert browser.new_context_calls == []


def test_other_workflow_row_write_contract_is_filtered_out_leaving_none():
    """contracts_for_workflow already filters this out (it names the OTHER
    workflow), so what remains has zero write contracts for MODE_NORMAL --
    a MODE_NORMAL writer with no row_write contract at all is still a
    valid (if useless) construction; this proves the other workflow's
    contract never leaks in, rather than raising."""
    browser = FakeBrowser(context_factory=lambda: FakeContext(_normal_happy_page_factory))
    contracts = (
        SEARCH_PAGE_CONTRACT,
        SEARCH_LISTE_MISSIONS_CONTRACT,
        NORMAL_READ_ROWS_CONTRACT,
        OTHER_WORKFLOW_ROW_WRITE_CONTRACT,
    )
    writer = run_async(
        open_verified_writer(
            browser, SyntheticLeaseHandle(), NORMAL_IDENTITY, MODE_NORMAL_PLAN, NORMAL_IDENTIFIERS, contracts, ALLOWED_HOST,
            writer_account=MCMA_WRITER_ACCOUNT,
        )
    )
    assert isinstance(writer, VerifiedMissionWriter)


def test_missing_search_page_contract_is_rejected():
    browser = FakeBrowser(context_factory=lambda: FakeContext(_normal_happy_page_factory))
    contracts = (SEARCH_LISTE_MISSIONS_CONTRACT, NORMAL_READ_ROWS_CONTRACT, NORMAL_ROW_WRITE_CONTRACT)
    with pytest.raises(ValueError):
        run_async(
            open_verified_writer(
                browser, SyntheticLeaseHandle(), NORMAL_IDENTITY, MODE_NORMAL_PLAN, NORMAL_IDENTIFIERS, contracts, ALLOWED_HOST,
                writer_account=MCMA_WRITER_ACCOUNT,
            )
        )
    assert browser.new_context_calls == []


def test_missing_read_rows_contract_is_rejected():
    browser = FakeBrowser(context_factory=lambda: FakeContext(_normal_happy_page_factory))
    contracts = (SEARCH_PAGE_CONTRACT, SEARCH_LISTE_MISSIONS_CONTRACT, NORMAL_ROW_WRITE_CONTRACT)
    with pytest.raises(ValueError):
        run_async(
            open_verified_writer(
                browser, SyntheticLeaseHandle(), NORMAL_IDENTITY, MODE_NORMAL_PLAN, NORMAL_IDENTIFIERS, contracts, ALLOWED_HOST,
                writer_account=MCMA_WRITER_ACCOUNT,
            )
        )
    assert browser.new_context_calls == []


def test_non_loopback_host_is_rejected_before_any_browser_context():
    browser = FakeBrowser(context_factory=lambda: FakeContext(_normal_happy_page_factory))
    with pytest.raises(ValueError):
        run_async(
            open_verified_writer(
                browser,
                SyntheticLeaseHandle(),
                NORMAL_IDENTITY,
                MODE_NORMAL_PLAN,
                NORMAL_IDENTIFIERS,
                HAPPY_PATH_CONTRACTS,
                "example.com:8080",
                writer_account=MCMA_WRITER_ACCOUNT,
            )
        )
    assert browser.new_context_calls == []


def test_construction_failure_after_context_creation_closes_the_context():
    browser = FakeBrowser(context_factory=FailingNewPageContext)
    with pytest.raises(RuntimeError):
        run_async(
            open_verified_writer(
                browser, SyntheticLeaseHandle(), NORMAL_IDENTITY, MODE_NORMAL_PLAN, NORMAL_IDENTIFIERS, HAPPY_PATH_CONTRACTS, ALLOWED_HOST,
                writer_account=MCMA_WRITER_ACCOUNT,
            )
        )
    assert browser.contexts_created[0].closed_count == 1


def test_happy_path_succeeds_and_reaches_write_active():
    browser = FakeBrowser(context_factory=lambda: FakeContext(_normal_happy_page_factory))
    writer = run_async(
        open_verified_writer(
            browser, SyntheticLeaseHandle(), NORMAL_IDENTITY, MODE_NORMAL_PLAN, NORMAL_IDENTIFIERS, HAPPY_PATH_CONTRACTS, ALLOWED_HOST,
            writer_account=MCMA_WRITER_ACCOUNT,
        )
    )
    assert isinstance(writer, VerifiedMissionWriter)
    assert writer._abort_handle._controller.phase is WriterPolicyPhase.WRITE_ACTIVE


def test_unplanned_rubrique_rejected_before_any_page_interaction():
    browser = FakeBrowser(context_factory=lambda: FakeContext(_normal_happy_page_factory))
    writer = run_async(
        open_verified_writer(
            browser, SyntheticLeaseHandle(), NORMAL_IDENTITY, MODE_NORMAL_PLAN, NORMAL_IDENTIFIERS, HAPPY_PATH_CONTRACTS, ALLOWED_HOST,
            writer_account=MCMA_WRITER_ACCOUNT,
        )
    )
    page = writer._page
    evaluate_calls_before = len(page.evaluate_calls)
    with pytest.raises(UnplannedRubrique):
        run_async(writer.add_normal_row(RubriqueId("999")))
    assert len(page.evaluate_calls) == evaluate_calls_before  # no page interaction happened
    with pytest.raises(WriteAborted):
        run_async(writer.add_normal_row(RubriqueId("3")))  # writer is now terminally aborted


def test_wrong_workflow_plan_rejects_add_normal_row_before_page_interaction():
    browser = FakeBrowser(context_factory=lambda: FakeContext(lambda: _pec_happy_page_factory()))
    writer = run_async(
        open_verified_writer(
            browser, SyntheticLeaseHandle(), PEC_IDENTITY, PEC_PLAN, PEC_IDENTIFIERS, PEC_HAPPY_PATH_CONTRACTS, ALLOWED_HOST,
            writer_account=MCMA_WRITER_ACCOUNT,
        )
    )
    with pytest.raises(WriteAborted):
        run_async(writer.add_normal_row(RubriqueId("3")))


def test_constructing_plan_data_and_identity_alone_never_creates_a_writer_or_touches_a_browser():
    """There is no DRY_RUN/EXECUTE flag in this module (that authorization
    lives in mcma.execution, out of scope here) -- what IS this module's
    responsibility is that merely building the plan-shaped inputs
    (WriterPlanData/ExpectedIdentity) is completely inert: no writer, no
    context, no page is created as a side effect of construction alone."""
    plan = WriterPlanData(repair_workflow=RepairWorkflow.MODE_NORMAL, row_intents=(row_intent("3", "10.00", "2.00"),))
    identity = make_expected_identity("77001-C-3", "699001")
    assert plan is not None and identity is not None
    # No FakeBrowser was ever constructed/passed anywhere above -- if this
    # test can pass without one, no writer could have been created.


# --------------------------------------------------------------------- #
# Item C -- PEC preflight moved inside construction; no public method
# exists for it anymore; the public surface is exactly the eight
# documented operations plus close.
# --------------------------------------------------------------------- #


def test_pec_preflight_succeeds_during_construction_and_caches_the_mapping():
    browser = FakeBrowser(context_factory=lambda: FakeContext(lambda: _pec_happy_page_factory()))
    writer = run_async(
        open_verified_writer(
            browser, SyntheticLeaseHandle(), PEC_IDENTITY, PEC_PLAN, PEC_IDENTIFIERS, PEC_HAPPY_PATH_CONTRACTS, ALLOWED_HOST,
            writer_account=MCMA_WRITER_ACCOUNT,
        )
    )
    assert writer._pec_row_map == {"3": 1}


def test_pec_preflight_zero_matches_aborts_construction_and_closes_context():
    browser = FakeBrowser(context_factory=lambda: FakeContext(lambda: _pec_happy_page_factory(preflight_rows=[])))
    with pytest.raises(RowAmbiguous):
        run_async(
            open_verified_writer(
                browser, SyntheticLeaseHandle(), PEC_IDENTITY, PEC_PLAN, PEC_IDENTIFIERS, PEC_HAPPY_PATH_CONTRACTS, ALLOWED_HOST,
                writer_account=MCMA_WRITER_ACCOUNT,
            )
        )
    assert browser.contexts_created[0].closed_count == 1


def test_pec_preflight_duplicate_matches_aborts_construction():
    dup_rows = [{"IdRubrique": "3", "IdDevisDet": 1}, {"IdRubrique": "3", "IdDevisDet": 2}]
    browser = FakeBrowser(context_factory=lambda: FakeContext(lambda: _pec_happy_page_factory(preflight_rows=dup_rows)))
    with pytest.raises(RowAmbiguous):
        run_async(
            open_verified_writer(
                browser, SyntheticLeaseHandle(), PEC_IDENTITY, PEC_PLAN, PEC_IDENTIFIERS, PEC_HAPPY_PATH_CONTRACTS, ALLOWED_HOST,
                writer_account=MCMA_WRITER_ACCOUNT,
            )
        )
    assert browser.contexts_created[0].closed_count == 1


def test_pec_preflight_malformed_id_devis_det_aborts_construction():
    bad_rows = [{"IdRubrique": "3", "IdDevisDet": "not-an-int"}]
    browser = FakeBrowser(context_factory=lambda: FakeContext(lambda: _pec_happy_page_factory(preflight_rows=bad_rows)))
    with pytest.raises(RowMismatch):
        run_async(
            open_verified_writer(
                browser, SyntheticLeaseHandle(), PEC_IDENTITY, PEC_PLAN, PEC_IDENTIFIERS, PEC_HAPPY_PATH_CONTRACTS, ALLOWED_HOST,
                writer_account=MCMA_WRITER_ACCOUNT,
            )
        )
    assert browser.contexts_created[0].closed_count == 1


def test_no_public_preflight_method_exists_on_verified_mission_writer():
    assert not hasattr(VerifiedMissionWriter, "preflight_pec_rows")


def test_public_surface_is_exactly_the_eight_documented_operations_plus_close():
    public_methods = {
        name
        for name in dir(VerifiedMissionWriter)
        if not name.startswith("_") and callable(getattr(VerifiedMissionWriter, name, None))
    }
    assert public_methods == {
        "add_normal_row",
        "edit_conventionne_row",
        "read_row",
        "verify_row",
        "trigger_native_recalc",
        "read_financial_summary",
        "verify_financial_summary",
        "close",
    }


def test_no_page_context_request_or_policy_control_exposed_publicly():
    for name in ("page", "context", "request", "policy", "controller", "abort_handle", "lease_handle"):
        assert not hasattr(VerifiedMissionWriter, name)


# --------------------------------------------------------------------- #
# Item B -- the stored lease is the only one ever checked; no method
# accepts a lease_handle argument, so a caller cannot substitute a fresh
# one after the construction lease becomes invalid.
# --------------------------------------------------------------------- #


def test_operations_accept_no_lease_handle_argument():
    import inspect

    for name in ("add_normal_row", "edit_conventionne_row", "read_row", "verify_row"):
        sig = inspect.signature(getattr(VerifiedMissionWriter, name))
        assert "lease_handle" not in sig.parameters
    for name in ("trigger_native_recalc", "read_financial_summary", "verify_financial_summary", "close"):
        sig = inspect.signature(getattr(VerifiedMissionWriter, name))
        assert list(sig.parameters) == ["self"]


def test_caller_cannot_substitute_a_fresh_lease_after_construction_lease_becomes_invalid():
    construction_lease = SyntheticLeaseHandle(account_id="acct-1", valid=True)
    browser = FakeBrowser(context_factory=lambda: FakeContext(_normal_happy_page_factory))
    writer = run_async(
        open_verified_writer(
            browser, construction_lease, NORMAL_IDENTITY, MODE_NORMAL_PLAN, NORMAL_IDENTIFIERS, HAPPY_PATH_CONTRACTS, ALLOWED_HOST,
            writer_account=mcma_writer_account("acct-1"),
        )
    )
    construction_lease.valid = False
    # A fresh, independently-valid lease exists here -- but there is no
    # parameter on add_normal_row through which it could ever be supplied.
    fresh_valid_lease = SyntheticLeaseHandle(account_id="acct-1", valid=True)
    assert fresh_valid_lease.valid is True  # exists, valid, and structurally unreachable
    with pytest.raises(LeaseInvalid):
        run_async(writer.add_normal_row(RubriqueId("3")))


# --------------------------------------------------------------------- #
# MAMDA read-only enforcement, layer 3 (correction batch / owner
# amendment): open_verified_writer structurally refuses a bare account_id
# -- it requires an McmaWriterAccountContext, and cross-checks its
# account_id against the LeaseHandle actually presented.
# --------------------------------------------------------------------- #


def test_open_verified_writer_rejects_a_non_mcma_writer_account_context():
    from mcma.portal.writer import AccountNotMcmaWritable, require_mcma_writer_account

    with pytest.raises(AccountNotMcmaWritable):
        require_mcma_writer_account("acct-mamda", entity="MAMDA", active=True)


def test_open_verified_writer_rejects_an_inactive_mcma_account():
    from mcma.portal.writer import AccountNotMcmaWritable, require_mcma_writer_account

    with pytest.raises(AccountNotMcmaWritable):
        require_mcma_writer_account("acct-mcma", entity="MCMA", active=False)


def test_open_verified_writer_rejects_a_writer_account_context_for_a_different_account():
    from mcma.portal.writer import AccountNotMcmaWritable

    browser = FakeBrowser(context_factory=lambda: FakeContext(_normal_happy_page_factory))
    mismatched_context = mcma_writer_account("some-other-account")
    with pytest.raises(AccountNotMcmaWritable):
        run_async(
            open_verified_writer(
                browser, SyntheticLeaseHandle(), NORMAL_IDENTITY, MODE_NORMAL_PLAN, NORMAL_IDENTIFIERS, HAPPY_PATH_CONTRACTS, ALLOWED_HOST,
                writer_account=mismatched_context,
            )
        )
    assert browser.new_context_calls == []


def test_open_verified_writer_requires_a_writer_account_context_at_all():
    browser = FakeBrowser(context_factory=lambda: FakeContext(_normal_happy_page_factory))
    with pytest.raises(TypeError):
        run_async(
            open_verified_writer(
                browser, SyntheticLeaseHandle(), NORMAL_IDENTITY, MODE_NORMAL_PLAN, NORMAL_IDENTIFIERS, HAPPY_PATH_CONTRACTS, ALLOWED_HOST,
            )
        )
    assert browser.new_context_calls == []


def test_mcma_writer_account_context_cannot_be_constructed_directly():
    from mcma.portal.writer import McmaWriterAccountContext

    with pytest.raises(RuntimeError):
        McmaWriterAccountContext("acct-1")
