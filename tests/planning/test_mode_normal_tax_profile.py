"""Mode Normal: agency-confirmed paint-material term and per-rubrique TVA profile.

Agency-confirmed rules pinned here:
  - "apprêt" (normalized "appret") is a paint material -> rubrique 16, even
    when Wexia labels its part_type as recuperation. Whole-word only.
  - TVA profile: 1, 2, 7, 8, 12, 28 -> 20 %; 3, 16 -> 0 %. Any other
    rubrique has no confirmed profile and fails closed (NeedsReview).
  - The declared total TVA is allocated only across the 20 % rows and must
    reconcile to 0.01 MAD; otherwise the plan fails closed.

All payloads are synthetic. The 8,000 MAD scenario reproduces the SHAPE of a
real dossier with every identifier replaced; no real data is stored here.
"""

import copy
import random
from decimal import Decimal

import pytest

from mcma.domain.rubriques import (
    MODE_NORMAL_ALLOWED_RUBRIQUES,
    MODE_NORMAL_TVA_RATES,
    classify_confirmed_paint_material,
)
from mcma.mapping.wexia import parse_wexia
from mcma.planning.plan import build_garage_conventionne_plan, build_mission_normal_plan


# --------------------------------------------------------------------- #
# Synthetic payload helpers (no real identifiers)
# --------------------------------------------------------------------- #


def _payload(lines, *, tax, mode="normal", parts=None, labour=None):
    ht = sum(Decimal(str(line["subtotal"])) for line in lines)
    tax = Decimal(str(tax))
    chiffrage = {
        "status": "approved",
        "scenario_type": "repair",
        "lignes_pieces": lines,
        "total_cost": str(ht),
        "tax_amount": str(tax),
        "final_cost": str(ht + tax),
    }
    if parts is not None:
        chiffrage["total_parts_cost"] = str(parts)
        chiffrage["total_labor_cost"] = str(labour)
    if mode == "normal":
        dossier: dict = {"mission_type": "normal", "incident_description": "MODE NORMAL"}
    else:
        dossier = {"mission_type": "garage conventionne", "incident_description": "PEC"}
    dossier.update({"id_sinistre": "900001", "reference": "REF-SYNTH-0001", "is_reform": False})
    return {
        "vehicule": {"license_plate": "11111-A-1"},
        "dossier": dossier,
        "chiffrages": [chiffrage],
    }


def _part(name, part_type, subtotal, is_original=None):
    line = {"item_type": "part", "item_name": name, "part_type": part_type, "subtotal": str(subtotal)}
    if is_original is not None:
        line["is_original"] = is_original
    return line


def _labour(family, subtotal):
    return {
        "item_type": "labor",
        "item_name": f"Main d'oeuvre {family}",
        "operation_type": family,
        "subtotal": str(subtotal),
    }


def _normal(payload):
    return build_mission_normal_plan(parse_wexia(payload))


def _rows(plan):
    return {step.rubrique_id.value: (step.ht.amount, step.tva.amount) for step in plan.steps}


def _reasons(plan):
    return [item.reason.value for item in plan.needs_review]


def _redacted_8000_lines():
    return [
        _part("Porte avant gauche", "recuperation", "5000.00", is_original=False),
        _part("Apprêt", "recuperation", "840.00", is_original=False),
        _labour("carrosserie", "1200.00"),
        _labour("peinture", "600.00"),
    ]


def _redacted_8000_payload(lines=None):
    return _payload(
        lines if lines is not None else _redacted_8000_lines(),
        tax="360.00",
        parts="5840.00",
        labour="1800.00",
    )


# --------------------------------------------------------------------- #
# The confirmed tax profile itself
# --------------------------------------------------------------------- #


def test_tva_profile_is_exactly_what_the_agency_confirmed():
    assert {r.value: rate for r, rate in MODE_NORMAL_TVA_RATES.items()} == {
        "1": Decimal("0.20"), "2": Decimal("0.20"),
        "3": Decimal("0"),
        "7": Decimal("0.20"), "8": Decimal("0.20"),
        "12": Decimal("0.20"), "28": Decimal("0.20"),
        "16": Decimal("0"),
    }


def test_every_profiled_rubrique_is_inside_the_mode_normal_policy():
    assert set(MODE_NORMAL_TVA_RATES) <= MODE_NORMAL_ALLOWED_RUBRIQUES


# --------------------------------------------------------------------- #
# Apprêt -> 16 (bounded, explicit)
# --------------------------------------------------------------------- #


@pytest.mark.parametrize("name", ["Apprêt", "apprêt", "APPRÊT", "appret", "Appret", "Apprêt gris 1L"])
def test_appret_is_a_confirmed_paint_material(name):
    assert getattr(classify_confirmed_paint_material(name), "value", None) == "16"


@pytest.mark.parametrize("name", [
    "", None, "apprete", "appretage", "apprets", "desappret",
    "porte", "aile avant", "peinture", "pistolet",
])
def test_paint_material_term_matching_is_whole_word_only(name):
    assert classify_confirmed_paint_material(name) is None


@pytest.mark.parametrize("name", ["Apprêt", "appret"])
@pytest.mark.parametrize("part_type", ["recuperation", "original", "adaptable", None])
def test_mode_normal_maps_appret_to_16_whatever_the_part_type(name, part_type):
    plan = _normal(_payload([_part(name, part_type, "840.00")], tax="0.00"))
    assert _reasons(plan) == []
    assert _rows(plan) == {"16": (Decimal("840.00"), Decimal("0.00"))}
    assert plan.is_writeable


def test_garage_conventionne_appret_behaviour_is_unchanged():
    """The confirmed term is scoped to Mode Normal; GC keeps origin mapping
    and the pre-existing global allocation."""
    plan = build_garage_conventionne_plan(
        parse_wexia(_payload([_part("Apprêt", "recuperation", "840.00")], tax="168.00", mode="gc"))
    )
    assert _rows(plan) == {"3": (Decimal("840.00"), Decimal("168.00"))}


# --------------------------------------------------------------------- #
# Redacted 8,000 MAD regression
# --------------------------------------------------------------------- #


def test_redacted_8000_dossier_plans_exactly():
    plan = _normal(_redacted_8000_payload())

    assert _reasons(plan) == []
    assert plan.is_writeable
    assert [s.rubrique_id.value for s in plan.steps] == ["3", "7", "12", "16"]
    assert _rows(plan) == {
        "3": (Decimal("5000.00"), Decimal("0.00")),
        "7": (Decimal("1200.00"), Decimal("240.00")),
        "12": (Decimal("600.00"), Decimal("120.00")),
        "16": (Decimal("840.00"), Decimal("0.00")),
    }
    ht = sum(s.ht.amount for s in plan.steps)
    tva = sum(s.tva.amount for s in plan.steps)
    ttc = sum(s.ht.amount + s.tva.amount for s in plan.steps)
    assert (ht, tva, ttc) == (Decimal("7640.00"), Decimal("360.00"), Decimal("8000.00"))


def test_redacted_8000_dossier_is_order_independent_and_deterministic():
    reference = _normal(_redacted_8000_payload())
    rng = random.Random(8000)
    for _ in range(10):
        lines = copy.deepcopy(_redacted_8000_lines())
        rng.shuffle(lines)
        plan = _normal(_redacted_8000_payload(lines))
        assert plan.steps == reference.steps
        assert plan.provenance.input_hash == reference.provenance.input_hash
        assert plan.provenance.plan_hash == reference.provenance.plan_hash
    assert _normal(_redacted_8000_payload()).canonical_json() == reference.canonical_json()


# --------------------------------------------------------------------- #
# 20 % rows and 0 % rows
# --------------------------------------------------------------------- #


def test_original_and_adaptable_parts_carry_20_percent():
    plan = _normal(_payload(
        [_part("aile", "original", "1000.00", is_original=True), _part("phare", "adaptable", "500.00")],
        tax="300.00",
    ))
    assert _reasons(plan) == []
    assert _rows(plan) == {
        "1": (Decimal("1000.00"), Decimal("200.00")),
        "2": (Decimal("500.00"), Decimal("100.00")),
    }


@pytest.mark.parametrize("family,rubrique", [
    ("carrosserie", "7"), ("mecanique", "8"), ("peinture", "12"), ("electrique", "28"),
])
def test_each_labour_family_carries_20_percent(family, rubrique):
    plan = _normal(_payload([_labour(family, "250.00")], tax="50.00"))
    assert _reasons(plan) == []
    assert _rows(plan) == {rubrique: (Decimal("250.00"), Decimal("50.00"))}


def test_recovered_parts_and_paint_materials_carry_zero_tva():
    plan = _normal(_payload(
        [_part("porte", "occasion", "1000.00"), _part("produits de peinture", None, "500.00")],
        tax="0.00",
    ))
    assert _reasons(plan) == []
    assert plan.is_writeable
    assert _rows(plan) == {
        "3": (Decimal("1000.00"), Decimal("0.00")),
        "16": (Decimal("500.00"), Decimal("0.00")),
    }


def test_remainder_cent_is_absorbed_only_by_taxable_rows():
    # 0.20 * 333.33 = 66.666 -> 66.67 each; declared 133.33 is within 0.01.
    plan = _normal(_payload(
        [_part("aile", "original", "333.33"), _labour("carrosserie", "333.33"),
         _part("porte", "occasion", "100.00")],
        tax="133.33",
    ))
    assert _reasons(plan) == []
    rows = _rows(plan)
    assert rows["3"][1] == Decimal("0.00")
    assert rows["1"][1] + rows["7"][1] == Decimal("133.33")
    assert all(step.tva.amount >= 0 for step in plan.steps)


# --------------------------------------------------------------------- #
# Fail closed
# --------------------------------------------------------------------- #


@pytest.mark.parametrize("line,rubrique", [
    ({"item_type": "part", "item_name": "PARE_BRISE", "repair_action": "remplacement"}, "22"),
    ({"item_type": "part", "item_name": "colle"}, "25"),
    ({"item_type": "labor", "item_name": "passage au marbre"}, "17"),
    ({"item_type": "labor", "item_name": "parallelisme"}, "18"),
])
def test_rubrique_without_confirmed_tax_profile_fails_closed(line, rubrique):
    plan = _normal(_payload([{**line, "subtotal": "100.00"}], tax="20.00"))
    assert [s.rubrique_id.value for s in plan.steps] == [rubrique]
    assert "UNCONFIRMED_TAX_PROFILE" in _reasons(plan)
    assert not plan.is_writeable
    assert all(step.tva.amount >= 0 for step in plan.steps)


def test_unconfirmed_row_alongside_confirmed_rows_still_fails_closed():
    plan = _normal(_payload(
        [_part("aile", "original", "100.00"), {"item_type": "part", "item_name": "colle", "subtotal": "50.00"}],
        tax="30.00",
    ))
    assert "UNCONFIRMED_TAX_PROFILE" in _reasons(plan)
    assert not plan.is_writeable


@pytest.mark.parametrize("tax", ["400.00", "359.98", "0.00", "432.00", "1528.00"])
def test_declared_tva_that_does_not_match_the_profile_fails_closed(tax):
    """432.00 / 1528.00 are what a 20 %-on-everything reading would give
    (with/without paint) -- the old global allocation's assumption."""
    payload = _redacted_8000_payload()
    chiffrage = payload["chiffrages"][0]
    chiffrage["tax_amount"] = tax
    chiffrage["final_cost"] = str(Decimal("7640.00") + Decimal(tax))
    plan = _normal(payload)
    assert "INVALID_TAX_ALLOCATION" in _reasons(plan)
    assert not plan.is_writeable
    assert all(step.tva.amount >= 0 for step in plan.steps)


def test_nonzero_tva_with_only_zero_rate_rows_fails_closed():
    plan = _normal(_payload([_part("porte", "occasion", "1000.00")], tax="200.00"))
    assert _reasons(plan) == ["INVALID_TAX_ALLOCATION"]
    assert _rows(plan) == {"3": (Decimal("1000.00"), Decimal("0.00"))}
    assert not plan.is_writeable


def test_explicit_rubric_id_conflicting_with_appret_fails_closed():
    """Wexia stating rubrique 3 for an apprêt line is a contradiction, not
    an override."""
    plan = _normal(_payload(
        [{**_part("Apprêt", "recuperation", "840.00"), "mcma_rubric_id": "3"}], tax="0.00"
    ))
    assert "UNKNOWN_RUBRIC_ID" in _reasons(plan)
    assert not plan.is_writeable
