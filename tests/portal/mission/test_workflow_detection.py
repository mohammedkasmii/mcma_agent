"""
INC-09A -- workflow detection. Ambiguity (both marker sets present, or
neither) always fails closed with WorkflowIndeterminate -- never resolved
by picking one. #VehRepareI is never queried at all (see mcma.portal.
mission's module docstring for the PORTAL_CONTRACT.md §4/§5 conflict this
avoids).
"""

import pytest

from mcma.domain.enums import RepairWorkflow
from mcma.portal import mission
from mcma.portal.mission import (
    WorkflowIndeterminate,
    WorkflowMismatch,
    detect_observed_workflow,
    require_workflow_agreement,
)
from mission_test_support import FakePage, run_async


def test_detects_mode_normal_when_only_normal_markers_present():
    page = FakePage(evaluate_results=[{"normal": True, "pec": False}])
    result = run_async(detect_observed_workflow(page))
    assert result is RepairWorkflow.MODE_NORMAL


def test_detects_garage_conventionne_when_only_pec_markers_present():
    page = FakePage(evaluate_results=[{"normal": False, "pec": True}])
    result = run_async(detect_observed_workflow(page))
    assert result is RepairWorkflow.GARAGE_CONVENTIONNE


def test_raises_indeterminate_when_both_present():
    """The stub-level positive control for INC-08's vacuous-safety lesson:
    the mock's DEFAULT rendering has both sections' DOM elements present
    (one merely hidden via CSS) -- this must fail closed, not silently
    resolve to one workflow."""
    page = FakePage(evaluate_results=[{"normal": True, "pec": True}])
    with pytest.raises(WorkflowIndeterminate):
        run_async(detect_observed_workflow(page))


def test_raises_indeterminate_when_neither_present():
    page = FakePage(evaluate_results=[{"normal": False, "pec": False}])
    with pytest.raises(WorkflowIndeterminate):
        run_async(detect_observed_workflow(page))


def test_require_workflow_agreement_passes_when_matching():
    require_workflow_agreement(RepairWorkflow.MODE_NORMAL, RepairWorkflow.MODE_NORMAL)  # no raise


def test_require_workflow_agreement_raises_mismatch_when_disagreeing():
    with pytest.raises(WorkflowMismatch) as exc_info:
        require_workflow_agreement(RepairWorkflow.MODE_NORMAL, RepairWorkflow.GARAGE_CONVENTIONNE)
    assert exc_info.value.planned is RepairWorkflow.MODE_NORMAL
    assert exc_info.value.observed is RepairWorkflow.GARAGE_CONVENTIONNE


def test_vehreparei_is_never_queried_by_detection():
    """Structural proof of the blocking finding's fix: #VehRepareI sits in
    the mission's SHARED header (present on both workflows), so including
    it in either marker set would make the gate pass vacuously. It must
    not appear anywhere in the detection markers or script."""
    assert "VehRepareI" not in mission._NORMAL_MARKERS
    assert "VehRepareI" not in mission._PEC_MARKERS
    assert "VehRepareI" not in mission._DETECT_WORKFLOW_JS


def test_normal_and_pec_marker_sets_are_disjoint_and_each_requires_both_members():
    assert set(mission._NORMAL_MARKERS).isdisjoint(mission._PEC_MARKERS)
    assert len(mission._NORMAL_MARKERS) >= 2
    assert len(mission._PEC_MARKERS) >= 2


def test_detection_script_takes_marker_lists_as_arguments_not_hardcoded_selectors():
    assert "querySelector" in mission._DETECT_WORKFLOW_JS
    # The script itself receives the marker lists as its parameter -- it
    # must not hardcode any selector string directly inline.
    for marker in mission._NORMAL_MARKERS + mission._PEC_MARKERS:
        assert marker not in mission._DETECT_WORKFLOW_JS
