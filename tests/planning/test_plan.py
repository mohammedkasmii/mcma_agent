"""INC-05 — deterministic, capability-neutral ProposedPlan (ADR-0002,
DOMAIN_MODEL §6): pure data, no mode/read_only, NeedsReview blocks
writeability, mandatory registration, no charge-mutuelle field."""

import dataclasses
import json
from pathlib import Path

import pytest

from mcma.domain.values import IdSinistre, InsurerReference, RegistrationPlate
from mcma.mapping.wexia import parse_wexia
from mcma.planning.plan import ExpectedIdentity, PlanBuildError, ProposedPlan, RowOp
from mcma.planning.registry import WorkflowRegistry, default_registry

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "characterization"
    / "wexia_normal_synthetic.json"
)


def _input(**overrides):
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    raw.pop("_comment", None)
    for dotted, value in overrides.items():
        target = raw
        parts = dotted.split(".")
        for part in parts[:-1]:
            target = target[part]
        target[parts[-1]] = value
    return raw


def _build(raw):
    return default_registry().get("mission_normal")(parse_wexia(raw))


def test_plan_builds_from_synthetic_fixture():
    plan = _build(_input())
    assert isinstance(plan, ProposedPlan)
    assert plan.needs_review == ()
    assert plan.is_writeable
    rubriques = [op.rubrique_id.value for op in plan.steps]
    assert rubriques == sorted(rubriques, key=int)
    assert plan.provenance.input_hash and plan.provenance.plan_hash


def test_plan_has_no_mode_or_read_only_field():
    field_names = {f.name for f in dataclasses.fields(ProposedPlan)}
    assert "mode" not in field_names
    assert "read_only" not in field_names
    plan = _build(_input())
    serialized = plan.canonical_json()
    assert '"mode"' not in serialized
    assert '"read_only"' not in serialized


def test_rowop_has_no_charge_mutuelle_field():
    field_names = {f.name.lower() for f in dataclasses.fields(RowOp)}
    assert field_names == {"rubrique_id", "ht", "tva", "vetuste", "source_pointers"}
    assert not any("charge" in n or "mutuelle" in n or "societaire" in n for n in field_names)


def test_needs_review_line_makes_plan_non_writeable():
    raw = _input()
    raw["chiffrages"][0]["lignes_pieces"].append(
        {"item_type": "part", "item_name": "piece mystere", "part_type": "inconnu", "subtotal": 10}
    )
    plan = _build(raw)
    assert plan.needs_review, "unknown part origin must surface as NeedsReview"
    assert not plan.is_writeable


def test_expected_identity_requires_registration_plate():
    with pytest.raises(TypeError):
        ExpectedIdentity(insurer_reference=InsurerReference("R-1"))  # no plate at all
    with pytest.raises(ValueError):
        ExpectedIdentity(registration=RegistrationPlate("11111-A-11"))  # no primary id
    identity = ExpectedIdentity(
        registration=RegistrationPlate("11111-A-11"),
        id_sinistre=IdSinistre("900001"),
    )
    assert identity.registration.normalized == "11111A11"


def test_missing_registration_in_input_fails_closed():
    raw = _input()
    raw["vehicule"]["license_plate"] = ""
    raw["dossier"].pop("license_plate", None)
    with pytest.raises(PlanBuildError):
        _build(raw)


def test_reform_and_conflicting_modes_fail_closed():
    with pytest.raises(PlanBuildError):
        _build(_input(**{"dossier.is_reform": True}))
    raw = _input(**{"dossier.mission_type": "normal et conventionne pec"})
    with pytest.raises(PlanBuildError):
        _build(raw)


def test_registry_unknown_workflow_fails_closed():
    registry = WorkflowRegistry()
    with pytest.raises(KeyError):
        registry.get("does-not-exist")
    assert callable(default_registry().get("mission_normal"))


def test_conventionne_dossier_rejected_by_normal_builder():
    """G1 review H1: the mission_normal builder must refuse a dossier whose
    explicit mode is conventionne instead of silently planning it."""
    raw = _input(
        **{
            "dossier.mission_type": "garage conventionne",
            "dossier.incident_description": "choc avant",
        }
    )
    with pytest.raises(PlanBuildError):
        _build(raw)


def test_absent_mode_signal_fails_closed():
    """G1 review H1: no explicit mode signal at all -> fail closed, never a
    silent 'normal' default."""
    raw = _input(
        **{"dossier.mission_type": None, "dossier.incident_description": "choc avant"}
    )
    with pytest.raises(PlanBuildError):
        _build(raw)


def test_pec_matches_only_as_standalone_word():
    """G1 review H1: 'inspection'/'respecter' must not trip the PEC token."""
    plan = _build(
        _input(**{"dossier.incident_description": "inspection du vehicule procedure normale"})
    )
    assert plan.is_writeable


def test_missing_tax_amount_fails_closed():
    """G1 review H3: absent/empty tax_amount is MISSING, not zero."""
    raw = _input()
    raw["chiffrages"][0]["tax_amount"] = ""
    with pytest.raises(PlanBuildError):
        _build(raw)
    raw = _input()
    del raw["chiffrages"][0]["tax_amount"]
    with pytest.raises(PlanBuildError):
        _build(raw)


def test_missing_is_reform_marker_fails_closed():
    """G1 review H4: the reform exclusion marker must be explicitly present."""
    raw = _input()
    del raw["dossier"]["is_reform"]
    with pytest.raises(PlanBuildError):
        _build(raw)


def test_all_lines_filtered_out_fails_closed():
    """G1 review M4: a writeable plan with zero steps must be impossible."""
    raw = _input()
    chiffrage = raw["chiffrages"][0]
    for line in chiffrage["lignes_pieces"]:
        line["subtotal"] = 0
    for line in chiffrage["lignes_mo"]:
        line["subtotal"] = 0
    chiffrage["total_cost"] = 0
    chiffrage["tax_amount"] = 0
    chiffrage["final_cost"] = 0
    with pytest.raises(PlanBuildError):
        _build(raw)


def test_ambiguous_chiffrage_selection_fails_closed():
    """G1 review H2: without an unambiguous approved winner, never pick
    candidates[0] by list order."""
    import copy

    raw = _input()
    first = copy.deepcopy(raw["chiffrages"][0])
    second = copy.deepcopy(raw["chiffrages"][0])
    first["status"] = "draft"
    second["status"] = "draft"
    second["id"] = "CH-SYN-9"
    second["total_cost"] = 999
    raw["chiffrages"] = [first, second]
    with pytest.raises(PlanBuildError):
        _build(raw)

def test_negative_subtotal_or_depreciation_fails_closed():
    # Negative subtotal piece
    raw = _input()
    raw["chiffrages"][0]["lignes_pieces"][0]["subtotal"] = -10
    with pytest.raises(PlanBuildError, match="negative"):
        _build(raw)

    # Negative subtotal mo
    raw = _input()
    raw["chiffrages"][0]["lignes_mo"][0]["subtotal"] = -10
    with pytest.raises(PlanBuildError, match="negative"):
        _build(raw)

    # Negative depreciation piece
    raw = _input()
    raw["chiffrages"][0]["lignes_pieces"][0]["depreciation_amount"] = -5
    with pytest.raises(PlanBuildError, match="negative"):
        _build(raw)

def test_proposed_plan_with_zero_steps_not_writeable():
    identity = ExpectedIdentity(registration=RegistrationPlate("11A11"), id_sinistre=IdSinistre("1"))
    from mcma.planning.plan import Provenance
    prov = Provenance(input_hash="1", plan_hash="2", builder_version="3")

    plan = ProposedPlan(
        expected_identity=identity,
        steps=(),
        needs_review=(),
        provenance=prov,
    )
    assert plan.is_writeable is False

def test_rowop_source_pointers_invariants():
    from mcma.core.money import Money
    from mcma.domain.values import RubriqueId
    with pytest.raises(ValueError, match="requires at least one source pointer"):
        RowOp(RubriqueId("1"), Money.ZERO, Money.ZERO, Money.ZERO, source_pointers=())
    with pytest.raises(ValueError, match="cannot be empty"):
        RowOp(RubriqueId("1"), Money.ZERO, Money.ZERO, Money.ZERO, source_pointers=("",))
    op = RowOp(RubriqueId("1"), Money.ZERO, Money.ZERO, Money.ZERO, source_pointers=("ptr",))
    assert op.source_pointers == ("ptr",)

def test_explicit_rubrique_versus_semantic_classification():
    """Explicit ID alone cannot provide missing semantic evidence and conflicting explicit ID fails closed."""
    # original ordinary part + explicit 4 -> NeedsReview
    raw = _input()
    line = raw["chiffrages"][0]["lignes_pieces"][0]
    line["is_original"] = True
    line["mcma_rubric_id"] = "4"
    plan = _build(raw)
    assert not plan.is_writeable
    assert any(r.reason.value == "UNKNOWN_RUBRIC_ID" for r in plan.needs_review)

    # original ordinary part + explicit 13 -> NeedsReview
    raw["chiffrages"][0]["lignes_pieces"][0]["mcma_rubric_id"] = "13"
    plan = _build(raw)
    assert not plan.is_writeable

    # original ordinary part + explicit 1 -> accepted
    raw["chiffrages"][0]["lignes_pieces"][0]["mcma_rubric_id"] = "1"
    plan = _build(raw)
    assert plan.is_writeable

    # corroborated pare-brise replacement + explicit 22 -> accepted
    raw = _input()
    line = raw["chiffrages"][0]["lignes_pieces"][0]
    line["item_name"] = "pare-brise"
    line["operation_type"] = "remplacement"
    line["mcma_rubric_id"] = "22"
    plan = _build(raw)
    assert plan.is_writeable

    # pare-brise replacement + explicit 20 -> NeedsReview
    raw["chiffrages"][0]["lignes_pieces"][0]["mcma_rubric_id"] = "20"
    plan = _build(raw)
    assert not plan.is_writeable
