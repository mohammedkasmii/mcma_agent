"""Real Wexia dossiers do not look like the fixtures.

Three shapes found in five real files, each of which made deterministic
data fail closed for no good reason:

  * labour arrives as item_type='labor' with BOTH structured family
    fields null, and no lignes_mo at all
  * the operation lives in repair_action while operation_type is null
  * an archived historical estimate sits beside the current one and
    competes with it

Everything that should still fail closed is asserted here too. Widening
these three cases must not widen anything else.
"""

import pytest

from mcma.domain.rubriques import classify_labour_line, classify_glass_line
from mcma.mapping.wexia import WexiaChiffrage, WexiaPieceLine
from mcma.planning.plan import PlanBuildError, _select_chiffrage


def _labour(text, operation_type=None, labor_type_id=None, item_type="labor"):
    return classify_labour_line(operation_type, labor_type_id, item_type, text)


def _rubrique(result):
    return getattr(getattr(result, "value", None), "value", None)


def _reason(result):
    return getattr(getattr(result, "reason", None), "value", None)


# --------------------------------------------------------------------- #
# Labour: item_type='labor' with no structured family
# --------------------------------------------------------------------- #


@pytest.mark.parametrize("text,expected", [
    ("carrosserie", "7"),
    ("tolerie", "7"),
    ("peinture", "12"),
    ("mecanique", "8"),
    ("electrique", "28"),
    ("electricite", "28"),
    ("marbre", "17"),
    ("parallelisme", "18"),
    ("equilibrage", "18"),
    ("geometrie", "18"),
])
def test_declared_labour_with_one_family_word_classifies(text, expected):
    """item_type='labor' supplies the MARKER -- Wexia has already said the
    line is labour, more reliably than a phrase in free text could. The
    family still has to come from the existing token lists."""
    assert _rubrique(_labour(text)) == expected


def test_declared_labour_without_a_family_stays_unknown():
    """No new keywords. "reparation" is not evidence of carrosserie, and
    is exactly the broad rule that must not come back."""
    assert _reason(_labour("reparation diverse")) == "UNKNOWN_LABOUR"
    assert _reason(_labour("forfait")) == "UNKNOWN_LABOUR"
    assert _reason(_labour("")) == "UNKNOWN_LABOUR"


def test_declared_labour_with_two_families_contradicts():
    assert _reason(_labour("carrosserie et peinture")) == "CONTRADICTORY_LABOUR"


def test_an_unknown_structured_value_never_falls_back_to_text():
    """The distinction the whole change rests on: a structured field that
    is ABSENT is not a structured field that is UNRECOGNISED. Falling back
    on the second would let an unknown external code be silently
    reinterpreted by free text."""
    result = _labour("carrosserie", operation_type="UNKNOWN_EXTERNAL_CODE")
    assert _reason(result) == "UNKNOWN_LABOUR"
    assert _rubrique(result) is None

    result = _labour("peinture", labor_type_id="SOME_OTHER_CODE")
    assert _reason(result) == "UNKNOWN_LABOUR"


def test_a_recognised_structured_family_still_wins():
    assert _rubrique(_labour("", operation_type="carrosserie")) == "7"
    assert _rubrique(_labour("", labor_type_id="peinture")) == "12"


def test_text_may_validate_but_never_override_a_structured_family():
    assert _reason(_labour("peinture", operation_type="carrosserie")) == "CONTRADICTORY_LABOUR"
    assert _rubrique(_labour("carrosserie", operation_type="carrosserie")) == "7"


def test_conflicting_structured_fields_still_contradict():
    assert _reason(
        _labour("", operation_type="carrosserie", labor_type_id="peinture")
    ) == "CONTRADICTORY_LABOUR"


def test_a_family_word_on_a_non_labour_line_classifies_nothing():
    """The marker comes from item_type='labor'. A part that merely
    mentions carrosserie is not labour."""
    assert _reason(_labour("carrosserie", item_type="part")) == "UNKNOWN_LABOUR"
    assert _reason(_labour("peinture", item_type=None)) == "UNKNOWN_LABOUR"


# --------------------------------------------------------------------- #
# Glass: repair_action is operation evidence
# --------------------------------------------------------------------- #


def _glass(item_name, operation_type=None, repair_action=None, notes=""):
    from mcma.planning.plan import _glass_operation_evidence

    line = WexiaPieceLine(
        item_type="part", item_name=item_name, operation_type=operation_type,
        repair_action=repair_action, notes=notes,
    )
    return classify_glass_line(line.item_name, _glass_operation_evidence(line))


@pytest.mark.parametrize("component,action,expected", [
    ("PARE_BRISE", "remplacement", "22"),
    ("PARE_BRISE", "reparation", "21"),
    ("VITRE laterale", "remplacement", "20"),
    ("VITRE laterale", "reparation", "19"),
    ("LUNETTE ARRIERE", "remplacement", "24"),
    ("LUNETTE ARRIERE", "reparation", "23"),
])
def test_repair_action_resolves_the_glass_operation(component, action, expected):
    """These rows came out AMBIGUOUS_GLASS because operation_type was null
    and repair_action was discarded by extra="ignore"."""
    assert _rubrique(_glass(component, repair_action=action)) == expected


def test_conflicting_operation_evidence_fails_closed():
    """Joining the sources rather than preferring one is what makes this
    ambiguous. Preferring operation_type would have quietly resolved the
    contradiction in its favour."""
    result = _glass("PARE_BRISE", operation_type="reparation", repair_action="remplacement")
    assert _reason(result) == "AMBIGUOUS_GLASS"


def test_glass_with_no_operation_evidence_at_all_is_still_ambiguous():
    assert _reason(_glass("PARE_BRISE")) == "AMBIGUOUS_GLASS"


def test_notes_are_still_read_as_operation_evidence():
    assert _rubrique(_glass("PARE_BRISE", notes="remplacement")) == "22"


def test_the_matrix_is_unchanged():
    from mcma.domain.rubriques import _GLASS_MATRIX

    assert len(_GLASS_MATRIX) == 6
    assert {r.value for r in _GLASS_MATRIX.values()} == {"19", "20", "21", "22", "23", "24"}


def test_replacement_is_never_inferred_from_part_type():
    """part_type='original' says where a part came from, not what was done
    to it."""
    line = WexiaPieceLine(
        item_type="part", item_name="PARE_BRISE", part_type="original", is_original=True,
    )
    from mcma.planning.plan import _glass_operation_evidence

    assert _glass_operation_evidence(line) == ""
    assert _reason(classify_glass_line(line.item_name, "")) == "AMBIGUOUS_GLASS"


def test_ordinary_parts_are_unaffected():
    from mcma.domain.rubriques import classify_ordinary_part

    assert _rubrique(classify_ordinary_part(part_type="original", is_original=True)) == "1"
    assert _rubrique(classify_ordinary_part(part_type="adaptable", is_original=False)) == "2"


# --------------------------------------------------------------------- #
# Archived chiffrages
# --------------------------------------------------------------------- #


def _chiffrage(**kwargs):
    kwargs.setdefault(
        "lignes_pieces",
        [WexiaPieceLine(item_type="part", item_name="X", subtotal="10")],
    )
    return WexiaChiffrage(**kwargs)


def test_repair_action_and_archival_fields_survive_parsing():
    """extra="ignore" silently dropped both, which is why the data looked
    ambiguous when it was not."""
    line = WexiaPieceLine(item_type="part", item_name="X", repair_action="remplacement")
    assert line.repair_action == "remplacement"
    chiffrage = _chiffrage(status="approved", archived_at="2026-01-01T00:00:00Z", archive_cycle=2)
    assert chiffrage.archived_at == "2026-01-01T00:00:00Z"
    assert chiffrage.archive_cycle == 2
    assert _chiffrage(status="approved").archived_at is None


def test_an_archived_approved_repair_does_not_compete_with_the_active_one():
    archived = _chiffrage(id="old", status="approved", scenario_type="repair",
                          archived_at="2026-01-01T00:00:00Z", archive_cycle=2)
    active = _chiffrage(id="current", status="approved", scenario_type="repair")
    assert _select_chiffrage([archived, active]).id == "current"


def test_an_archived_candidate_is_excluded_even_when_it_is_final():
    archived = _chiffrage(id="old", status="approved", is_final=True,
                          archived_at="2026-01-01T00:00:00Z")
    active = _chiffrage(id="current", status="approved")
    assert _select_chiffrage([archived, active]).id == "current"


def test_an_archived_draft_leaves_the_active_submitted_one_deterministic():
    """Mirrors the fifth real dossier: a retired draft beside a live
    submitted estimate."""
    archived = _chiffrage(id="draft", status="draft", scenario_type="replacement",
                          archived_at="2026-01-01T00:00:00Z")
    active = _chiffrage(id="submitted", status="submitted", scenario_type="repair")
    assert _select_chiffrage([archived, active]).id == "submitted"


def test_two_active_approved_candidates_still_fail_closed():
    """Archival filtering only. No preference for repair over replacement,
    for devis over facture, for the newest or the highest version -- none
    of that is proven, and inventing it is how the wrong estimate gets
    filled into a claim."""
    repair = _chiffrage(id="repair", status="approved", scenario_type="repair")
    replacement = _chiffrage(id="replacement", status="approved", scenario_type="replacement")
    with pytest.raises(PlanBuildError, match="multiple distinct approved chiffrages"):
        _select_chiffrage([repair, replacement])


def test_archive_cycle_alone_is_not_treated_as_archival():
    """archived_at is the explicit marker. A cycle number is metadata."""
    cycled = _chiffrage(id="cycled", status="approved", scenario_type="repair", archive_cycle=2)
    other = _chiffrage(id="other", status="approved", scenario_type="replacement")
    with pytest.raises(PlanBuildError):
        _select_chiffrage([cycled, other])


def test_everything_archived_fails_closed_rather_than_picking_one():
    archived = _chiffrage(id="a", status="approved", archived_at="2026-01-01T00:00:00Z")
    with pytest.raises(PlanBuildError, match="no detailed repair chiffrage"):
        _select_chiffrage([archived])


def test_an_empty_archived_at_string_is_not_archival():
    """Absent, null and empty all mean "not archived"; only a real value
    retires a version."""
    active = _chiffrage(id="current", status="approved", archived_at="")
    assert _select_chiffrage([active]).id == "current"
