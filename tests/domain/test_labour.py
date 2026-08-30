"""INC-04 — labour detection (B.7): structured-first; explicit labour
expressions only; generic family words alone insufficient; no unrestricted
'mo' substring; unknown/contradictory fails closed."""

from mcma.domain.enums import LabourFamily
from mcma.domain.results import Mapped, NeedsReview, ReasonCode
from mcma.domain.rubriques import classify_labour_line, labour_rubrique
from mcma.domain.values import RubriqueId

FAMILY_RUBRIQUE = {
    LabourFamily.TOLERIE_CARROSSERIE: "7",
    LabourFamily.MECANIQUE: "8",
    LabourFamily.PEINTURE: "12",
    LabourFamily.ELECTRIQUE: "28",
    LabourFamily.MARBRE: "17",
    LabourFamily.PARALLELISME_EQUILIBRAGE: "18",
}


def test_labour_family_rubrique_table():
    for family, rubrique in FAMILY_RUBRIQUE.items():
        assert labour_rubrique(family) == RubriqueId(rubrique)


def test_structured_item_type_operation_type_decides_family():
    """A structured family decides directly; free text may not override it."""
    result = classify_labour_line(operation_type="peinture", labor_type_id=None, item_type=None, text="retouche")
    assert result == Mapped(RubriqueId("12"))
    result = classify_labour_line(operation_type=None, labor_type_id="electrique", item_type=None, text="")
    assert result == Mapped(RubriqueId("28"))


def test_text_contradicting_structured_family_fails_closed():
    result = classify_labour_line(
        operation_type="peinture", labor_type_id=None, item_type=None, text="MO mécanique"
    )
    assert isinstance(result, NeedsReview)
    assert result.reason is ReasonCode.CONTRADICTORY_LABOUR


def test_explicit_labour_expressions_classify():
    cases = {
        "main d'oeuvre carrosserie": "7",
        "MO tôlerie": "7",
        "forfait main d'oeuvre peinture": "12",
        "heures de main d'oeuvre mécanique": "8",
        "MO électrique": "28",
        "passage au marbre": "17",
        "parallélisme et équilibrage": "18",
        "débosselage aile": "7",
        "redressage longeron": "7",
    }
    for text, rubrique in cases.items():
        result = classify_labour_line(operation_type=None, labor_type_id=None, item_type=None, text=text)
        assert result == Mapped(RubriqueId(rubrique)), (text, result)


def test_generic_peinture_mecanique_electrique_alone_insufficient():
    for text in ("peinture", "mécanique", "électrique", "peinture aile avant"):
        result = classify_labour_line(operation_type=None, labor_type_id=None, item_type=None, text=text)
        assert isinstance(result, NeedsReview), text
        assert result.reason is ReasonCode.UNKNOWN_LABOUR


def test_no_unrestricted_mo_substring():
    """F15 fixed: words merely containing 'mo' never classify as labour."""
    for text in ("module electronique", "moteur", "commande", "amovible", "modification"):
        result = classify_labour_line(operation_type=None, labor_type_id=None, item_type=None, text=text)
        assert isinstance(result, NeedsReview), text
        assert result.reason is ReasonCode.UNKNOWN_LABOUR


def test_unknown_or_contradictory_labour_fails_closed():
    result = classify_labour_line(operation_type=None, labor_type_id=None, item_type=None, text="")
    assert isinstance(result, NeedsReview)
    assert result.reason is ReasonCode.UNKNOWN_LABOUR

    # Two explicit labour families in one line: contradictory.
    result = classify_labour_line(
        operation_type=None, labor_type_id=None, item_type=None, text="MO peinture et MO mécanique"
    )
    assert isinstance(result, NeedsReview)
    assert result.reason is ReasonCode.CONTRADICTORY_LABOUR

def test_unknown_structured_value_fails_closed_never_fallback():
    # A present but unknown structured value -> NeedsReview, never fallback
    result = classify_labour_line(operation_type="unknown-op", labor_type_id=None, item_type=None, text="MO peinture")
    assert isinstance(result, NeedsReview)
    assert result.reason is ReasonCode.UNKNOWN_LABOUR

def test_conflicting_structured_fields_fail_closed():
    # Conflicting recognized structured values -> CONTRADICTORY_LABOUR
    result = classify_labour_line(operation_type="peinture", labor_type_id="mecanique", item_type=None, text="")
    assert isinstance(result, NeedsReview)
    assert result.reason is ReasonCode.CONTRADICTORY_LABOUR

def test_structured_labour_completeness_rules():
    # operation_type=peinture + labor_type_id=unknown -> UNKNOWN_LABOUR
    result = classify_labour_line(operation_type="peinture", labor_type_id="unknown", item_type=None, text="")
    assert isinstance(result, NeedsReview)
    assert result.reason is ReasonCode.UNKNOWN_LABOUR

    # item_type=labour + missing operation_type/labor_type_id + notes “MO peinture” → UNKNOWN_LABOUR
    result = classify_labour_line(operation_type=None, labor_type_id=None, item_type="labor", text="MO peinture")
    assert isinstance(result, NeedsReview)
    assert result.reason is ReasonCode.UNKNOWN_LABOUR

    # item_type=part plus a conflicting structured labour family → NeedsReview
    result = classify_labour_line(operation_type="peinture", labor_type_id=None, item_type="part", text="MO mecanique")
    assert isinstance(result, NeedsReview)
    assert result.reason is ReasonCode.CONTRADICTORY_LABOUR

    # recognized consistent structured fields → correct rubrique
    result = classify_labour_line(operation_type="peinture", labor_type_id="peinture", item_type="labor", text="")
    assert result == Mapped(RubriqueId("12"))
