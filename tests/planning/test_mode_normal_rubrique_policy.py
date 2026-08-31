"""The Mode Normal automatic mapping surface is small, and origin-driven.

MCMA's full 28-rubrique catalog is its chart of accounts, not the set this
system may map to on its own. Conflating the two is precisely the old
mapper's mistake: SYSTEM_RUBRIQUE_MATRIX read an item's physical family
out of its name or system and produced 4/5/6, 10/11 or 13/14/15 from it,
so "moteur original" became a mechanical rubrique instead of an origin
one. BUSINESS_RULES.md records that as a contradiction.

These tests pin the agency's actual rule and, more importantly, pin that
the old one cannot come back one plausible keyword at a time.
"""

import pytest

from mcma.domain.rubriques import (
    MODE_NORMAL_ALLOWED_RUBRIQUES,
    MODE_NORMAL_EXCEPTION_RUBRIQUES,
    MODE_NORMAL_FORBIDDEN_RUBRIQUES,
    MODE_NORMAL_LABOUR_RUBRIQUES,
    MODE_NORMAL_PART_RUBRIQUES,
    classify_labour_line,
    classify_ordinary_part,
)
from mcma.planning.plan import PlanBuildError

FORBIDDEN = {"4", "5", "6", "9", "10", "11", "13", "14", "15"}


def _codes(rubriques):
    return {r.value for r in rubriques}


def _rubrique(result):
    return getattr(getattr(result, "value", None), "value", None)


# --------------------------------------------------------------------- #
# The policy itself
# --------------------------------------------------------------------- #


def test_the_mode_normal_surface_is_exactly_what_the_agency_confirmed():
    assert _codes(MODE_NORMAL_PART_RUBRIQUES) == {"1", "2", "3"}
    assert _codes(MODE_NORMAL_LABOUR_RUBRIQUES) == {"7", "8", "12", "28"}
    assert _codes(MODE_NORMAL_EXCEPTION_RUBRIQUES) == {
        "16", "17", "18", "19", "20", "21", "22", "23", "24", "25", "26", "27",
    }
    assert _codes(MODE_NORMAL_ALLOWED_RUBRIQUES) == {
        "1", "2", "3", "7", "8", "12", "16", "17", "18",
        "19", "20", "21", "22", "23", "24", "25", "26", "27", "28",
    }


def test_the_catalog_is_not_the_mapping_surface():
    """The distinction the whole policy rests on."""
    assert _codes(MODE_NORMAL_FORBIDDEN_RUBRIQUES) == FORBIDDEN
    assert not (MODE_NORMAL_ALLOWED_RUBRIQUES & MODE_NORMAL_FORBIDDEN_RUBRIQUES)


def test_rubrique_9_is_a_total_and_never_a_line():
    assert "9" in _codes(MODE_NORMAL_FORBIDDEN_RUBRIQUES)


# --------------------------------------------------------------------- #
# Ordinary pieces: origin decides, and nothing else does
# --------------------------------------------------------------------- #

PHYSICAL_FAMILIES = [
    "moteur", "batterie", "radiateur", "alternateur", "phare", "porte",
    "aile avant", "pare-choc", "cablage electrique", "boite de vitesses",
]


@pytest.mark.parametrize("item_name", PHYSICAL_FAMILIES)
@pytest.mark.parametrize("part_type,is_original,expected", [
    ("original", True, "1"),
    ("origine", True, "1"),
    ("adaptable", False, "2"),
    ("recuperable", False, "3"),
    ("occasion", False, "3"),
])
def test_origin_alone_decides_an_ordinary_piece(item_name, part_type, is_original, expected):
    """The item's physical family is irrelevant. A moteur, a batterie and
    a porte all map by where the part came from."""
    assert _rubrique(classify_ordinary_part(part_type=part_type, is_original=is_original)) == expected


def test_a_mechanical_part_is_never_a_mechanical_rubrique():
    """The single clearest case of the old mistake: moteur + original is
    1, not 4/5/6."""
    result = _rubrique(classify_ordinary_part(part_type="original", is_original=True))
    assert result == "1"
    assert result not in FORBIDDEN


def test_an_electrical_part_is_never_an_electrical_rubrique():
    """batterie + original is 1, not 13/14/15."""
    result = _rubrique(classify_ordinary_part(part_type="original", is_original=True))
    assert result == "1"
    assert result not in FORBIDDEN


def test_an_adaptable_mechanical_part_is_2_not_5():
    assert _rubrique(classify_ordinary_part(part_type="adaptable", is_original=False)) == "2"


def test_ordinary_part_classification_takes_no_descriptive_input_at_all():
    """Structural proof rather than keyword-by-keyword: the function has
    no parameter through which a name, system or category could reach it,
    so it cannot be influenced by one."""
    import inspect

    parameters = set(inspect.signature(classify_ordinary_part).parameters)
    assert parameters == {"part_type", "is_original"}


# --------------------------------------------------------------------- #
# Ordinary pieces do not become labour
# --------------------------------------------------------------------- #


@pytest.mark.parametrize("item_name", ["moteur", "batterie electrique", "cable electrique"])
def test_a_part_whose_name_mentions_a_labour_family_is_not_labour(item_name):
    result = classify_labour_line(None, None, "part", item_name)
    assert _rubrique(result) is None
    assert result.reason.value == "UNKNOWN_LABOUR"


# --------------------------------------------------------------------- #
# The four normal labour families
# --------------------------------------------------------------------- #


@pytest.mark.parametrize("text,expected", [
    ("carrosserie", "7"), ("tolerie", "7"),
    ("mecanique", "8"), ("peinture", "12"),
    ("electrique", "28"), ("electricite", "28"),
])
def test_the_four_normal_labour_families(text, expected):
    assert _rubrique(classify_labour_line(None, None, "labor", text)) == expected
    assert expected in _codes(MODE_NORMAL_LABOUR_RUBRIQUES)


def test_generic_reparation_is_still_not_carrosserie():
    """The broad rule that must never come back."""
    assert classify_labour_line(None, None, "labor", "reparation").reason.value == "UNKNOWN_LABOUR"


def test_structured_evidence_remains_authoritative_and_fail_closed():
    assert _rubrique(classify_labour_line("carrosserie", None, "labor", "")) == "7"
    assert classify_labour_line(
        "UNKNOWN_EXTERNAL_CODE", None, "labor", "carrosserie"
    ).reason.value == "UNKNOWN_LABOUR"
    assert classify_labour_line(
        "carrosserie", "peinture", "labor", ""
    ).reason.value == "CONTRADICTORY_LABOUR"


# --------------------------------------------------------------------- #
# Exceptions need their own signal
# --------------------------------------------------------------------- #


def test_marbre_and_parallelisme_are_operations_not_labour_families():
    assert _rubrique(classify_labour_line(None, None, "labor", "marbre")) == "17"
    assert _rubrique(classify_labour_line(None, None, "labor", "parallelisme")) == "18"
    # Deliberately not counted among the four normal labour families.
    assert "17" not in _codes(MODE_NORMAL_LABOUR_RUBRIQUES)
    assert "18" not in _codes(MODE_NORMAL_LABOUR_RUBRIQUES)
    assert {"17", "18"} <= _codes(MODE_NORMAL_EXCEPTION_RUBRIQUES)


def test_paint_materials_are_16_but_a_painted_part_is_not():
    from mcma.domain.rubriques import classify_peinture_materials

    assert getattr(classify_peinture_materials("produits de peinture"), "value", None) == "16"
    # An ordinary part is unaffected by the word appearing in its text.
    assert classify_peinture_materials("aile originale") is None


def test_glass_needs_a_component_and_an_operation():
    from mcma.domain.rubriques import classify_glass_line

    assert _rubrique(classify_glass_line("PARE_BRISE", "remplacement")) == "22"
    # Component without operation stays ambiguous rather than guessing.
    assert classify_glass_line("PARE_BRISE", "").reason.value == "AMBIGUOUS_GLASS"


def test_part_type_is_origin_and_never_a_glass_operation():
    from mcma.domain.rubriques import classify_glass_line

    assert classify_glass_line("PARE_BRISE", "original").reason.value == "AMBIGUOUS_GLASS"


def test_conflicting_glass_operation_evidence_stays_ambiguous():
    from mcma.planning.plan import _glass_operation_evidence
    from mcma.domain.rubriques import classify_glass_line
    from mcma.mapping.wexia import WexiaPieceLine

    line = WexiaPieceLine(
        item_type="part", item_name="PARE_BRISE",
        operation_type="reparation", repair_action="remplacement",
    )
    result = classify_glass_line(line.item_name, _glass_operation_evidence(line))
    assert result.reason.value == "AMBIGUOUS_GLASS"


# --------------------------------------------------------------------- #
# Explicit mcma_rubric_id never overrides semantics
# --------------------------------------------------------------------- #


def _dossier(lines, **chiffrage):
    chiffrage.setdefault("status", "approved")
    chiffrage.setdefault("scenario_type", "repair")
    return {
        "vehicule": {"license_plate": "77001-C-3"},
        "dossier": {
            "id_sinistre": "699001", "mission_type": "normal",
            "incident_description": "MODE NORMAL", "is_reform": False,
        },
        "chiffrages": [dict(lignes_pieces=lines, **chiffrage)],
    }


def _plan(payload):
    from mcma.mapping.wexia import parse_wexia
    from mcma.planning.plan import build_mission_normal_plan

    return build_mission_normal_plan(parse_wexia(payload))


def _one_part(**overrides):
    line = {
        "item_type": "part", "item_name": "moteur",
        "part_type": "original", "is_original": True, "subtotal": "100",
    }
    line.update(overrides)
    return _dossier([line], tax_amount="20", total_cost="100", final_cost="120")


@pytest.mark.parametrize("explicit", ["4", "5", "6", "10", "11", "13", "14", "15"])
def test_an_explicit_forbidden_rubrique_conflicts_with_the_semantics(explicit):
    """An explicit id is not a licence to leave the policy. moteur +
    original is 1; anything else on that line is a contradiction."""
    plan = _plan(_one_part(mcma_rubric_id=explicit))
    reasons = [item.reason.value for item in plan.needs_review]
    assert "UNKNOWN_RUBRIC_ID" in reasons
    assert plan.steps == ()


def test_an_explicit_rubrique_that_agrees_is_accepted():
    plan = _plan(_one_part(mcma_rubric_id="1"))
    assert list(plan.needs_review) == []
    assert [step.rubrique_id.value for step in plan.steps] == ["1"]


def test_an_explicit_exception_rubrique_is_accepted_when_semantics_agree():
    payload = _dossier(
        [{"item_type": "part", "item_name": "PARE_BRISE", "repair_action": "remplacement",
          "mcma_rubric_id": "22", "subtotal": "100"}],
        tax_amount="20", total_cost="100", final_cost="120",
    )
    plan = _plan(payload)
    assert list(plan.needs_review) == []
    assert [step.rubrique_id.value for step in plan.steps] == ["22"]


def test_rubrique_9_is_refused_even_when_stated_explicitly():
    plan = _plan(_one_part(mcma_rubric_id="9"))
    assert [item.reason.value for item in plan.needs_review] == ["UNKNOWN_RUBRIC_ID"]


# --------------------------------------------------------------------- #
# The backstop
# --------------------------------------------------------------------- #


def test_a_mode_normal_plan_outside_the_policy_fails_closed(monkeypatch):
    """The classifiers already only produce allowed rubriques, so this
    proves the guard would CATCH a regression rather than that one exists
    -- a forbidden rubrique is forced in and the build must refuse."""
    import mcma.planning.plan as plan_module
    from mcma.domain.rubriques import RubriqueId

    real_core = plan_module._build_plan_core

    def _core_with_forbidden_row(typed_input, workflow):
        plan = real_core(typed_input, workflow)
        poisoned = tuple(
            step.__class__(**{**step.__dict__, "rubrique_id": RubriqueId("5")})
            for step in plan.steps
        )
        return plan.__class__(**{**plan.__dict__, "steps": poisoned})

    monkeypatch.setattr(plan_module, "_build_plan_core", _core_with_forbidden_row)

    with pytest.raises(PlanBuildError, match="outside the agency mapping policy"):
        _plan(_one_part())


def test_a_normal_plan_passes_the_backstop():
    plan = _plan(_one_part())
    assert [step.rubrique_id.value for step in plan.steps] == ["1"]


def test_garage_conventionne_is_not_subjected_to_the_mode_normal_policy():
    """Conventionné maps against pre-existing portal rows and is
    deliberately left alone by this patch."""
    import inspect

    from mcma.planning.plan import build_garage_conventionne_plan

    source = inspect.getsource(build_garage_conventionne_plan)
    assert "_enforce_mode_normal_rubrique_policy" not in source
