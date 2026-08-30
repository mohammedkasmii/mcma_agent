"""
INC-09A -- exactly-one mission search and mission-open navigation.
"""

import pytest

from mcma.portal.capabilities import SearchIdentifiers
from mcma.portal.mission import MissionCandidate, MissionSelectionError, open_candidate, search_exactly_one
from mission_test_support import ALLOWED_HOST, FakePage, run_async


def test_search_exactly_one_returns_the_single_candidate():
    page = FakePage(evaluate_results=[{"data": [{"IdMission": 1, "Matricule": "X", "ReferenceMission": "R", "Societaire": "S"}]}])
    candidate = run_async(search_exactly_one(page, ALLOWED_HOST, SearchIdentifiers(matricule="X")))
    assert candidate.id_mission == 1


def test_search_zero_candidates_fails_closed():
    page = FakePage(evaluate_results=[{"data": []}])
    with pytest.raises(MissionSelectionError) as exc_info:
        run_async(search_exactly_one(page, ALLOWED_HOST, SearchIdentifiers(matricule="nope")))
    assert exc_info.value.count == 0


def test_search_multiple_candidates_fails_closed():
    page = FakePage(
        evaluate_results=[
            {
                "data": [
                    {"IdMission": 1, "Matricule": "X", "ReferenceMission": "R1", "Societaire": "S1"},
                    {"IdMission": 2, "Matricule": "X", "ReferenceMission": "R2", "Societaire": "S2"},
                ]
            }
        ]
    )
    with pytest.raises(MissionSelectionError) as exc_info:
        run_async(search_exactly_one(page, ALLOWED_HOST, SearchIdentifiers(matricule="X")))
    assert exc_info.value.count == 2


def test_search_never_falls_back_to_first_or_sole_row():
    """F3/F4 regression: three candidates must still fail closed with the
    exact count, never silently resolving to candidates[0]."""
    page = FakePage(
        evaluate_results=[
            {
                "data": [
                    {"IdMission": 1, "Matricule": "X"},
                    {"IdMission": 2, "Matricule": "X"},
                    {"IdMission": 3, "Matricule": "X"},
                ]
            }
        ]
    )
    with pytest.raises(MissionSelectionError) as exc_info:
        run_async(search_exactly_one(page, ALLOWED_HOST, SearchIdentifiers(matricule="X")))
    assert exc_info.value.count == 3


def test_search_rejects_raw_dict_identifiers():
    page = FakePage()
    with pytest.raises(TypeError):
        run_async(search_exactly_one(page, ALLOWED_HOST, {"Matricule": "X"}))
    assert page.evaluate_calls == []


def test_search_skips_rows_without_id_mission():
    page = FakePage(evaluate_results=[{"data": [{"Matricule": "X"}]}])
    with pytest.raises(MissionSelectionError) as exc_info:
        run_async(search_exactly_one(page, ALLOWED_HOST, SearchIdentifiers(matricule="X")))
    assert exc_info.value.count == 0


def test_open_candidate_navigates_to_exact_deep_link():
    page = FakePage()
    candidate = MissionCandidate(id_mission=42, matricule="X", reference_mission="R", societaire="S")
    run_async(open_candidate(page, ALLOWED_HOST, candidate))
    assert page.goto_calls == [
        f"http://{ALLOWED_HOST}/SinAuto_MCMA/expertise/gestionExpert/getSinistre/idSinistre/42/rubrique/gestionexpert-index"
    ]


def test_open_candidate_percent_escapes_the_id_segment():
    page = FakePage()
    candidate = MissionCandidate(
        id_mission="../../gestiongarage/garageModifierValDevis",
        matricule="X",
        reference_mission="R",
        societaire="S",
    )
    run_async(open_candidate(page, ALLOWED_HOST, candidate))
    (url,) = page.goto_calls
    id_segment = url.split("idSinistre/", 1)[1].split("/rubrique")[0]
    assert "/" not in id_segment
