"""Pilot-integration correction (section 3) -- detect_workflow: the one
public function a job runner uses to determine the target workflow from
typed evidence, never a client-supplied/hardcoded workflow name."""

import pytest

from mcma.mapping.wexia import parse_wexia
from mcma.planning.plan import PlanBuildError, RepairWorkflow, detect_workflow


def test_detects_mode_normal_from_explicit_signal():
    raw = {"dossier": {"reference_number": "R1", "mission_type": "normal", "is_reform": False}}
    assert detect_workflow(parse_wexia(raw)) is RepairWorkflow.MODE_NORMAL


def test_detects_garage_conventionne_from_explicit_signal():
    raw = {"dossier": {"reference_number": "R1", "mission_type": "garage conventionne", "is_reform": False}}
    assert detect_workflow(parse_wexia(raw)) is RepairWorkflow.GARAGE_CONVENTIONNE


def test_fails_closed_when_no_signal_present():
    raw = {"dossier": {"reference_number": "R1", "is_reform": False}}
    with pytest.raises(PlanBuildError):
        detect_workflow(parse_wexia(raw))


def test_fails_closed_on_conflicting_signals():
    raw = {
        "dossier": {
            "reference_number": "R1",
            "mission_type": "normal",
            "repair_mode": "garage conventionne",
            "is_reform": False,
        }
    }
    with pytest.raises(PlanBuildError):
        detect_workflow(parse_wexia(raw))


def test_agrees_with_the_builders_own_internal_detection():
    """detect_workflow must never pick a workflow that the corresponding
    build_*_plan function would then reject as mismatched -- proven here
    by building the plan with the detected workflow's own builder."""
    from mcma.planning.plan import build_mission_normal_plan

    raw = {
        "dossier": {"reference_number": "R1", "mission_type": "normal", "is_reform": False},
        "vehicule": {"license_plate": "11111-A-11"},
        "chiffrages": [
            {
                "status": "approved", "is_final": True, "scenario_type": "repair",
                "total_cost": 10, "tax_amount": 2,
                "lignes_pieces": [{"item_type": "part", "item_name": "x", "part_type": "original", "subtotal": 10}],
            }
        ],
    }
    typed_input = parse_wexia(raw)
    workflow = detect_workflow(typed_input)
    assert workflow is RepairWorkflow.MODE_NORMAL
    plan = build_mission_normal_plan(typed_input)  # must not raise
    assert plan is not None
