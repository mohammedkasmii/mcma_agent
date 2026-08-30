"""INC-04 — colle/kit classification (25/26/27), catalog integrity, and
out-of-catalogue fail-closed (B.4)."""

from mcma.domain.results import Mapped, NeedsReview, ReasonCode
from mcma.domain.rubriques import (
    RUBRIQUE_CATALOG,
    classify_colle,
    resolve_explicit_rubrique,
)
from mcma.domain.values import RubriqueId


def test_colle_25_kit_26_kit_vitre_27():
    assert classify_colle("colle parebrise") == RubriqueId("25")
    assert classify_colle("mastic") == RubriqueId("25")
    assert classify_colle("kit colle pare-brise") == RubriqueId("26")
    assert classify_colle("KIT COLLE VITRE") == RubriqueId("27")
    assert classify_colle("aile avant") is None
    assert classify_colle("") is None


def test_catalog_has_28_entries_matching_recovery_doc():
    assert len(RUBRIQUE_CATALOG) == 28
    assert RUBRIQUE_CATALOG["1"] == "FOURNITURES CARROSSERIE (ORIGINES)"
    assert RUBRIQUE_CATALOG["22"] == "REMPLACEMENT PARE-BRISE"
    assert RUBRIQUE_CATALOG["28"] == "MAIN D'OEUVRE ELECTRIQUE"


def test_out_of_catalogue_rubric_id_fails_closed():
    """B.4 / F14 fixed: an explicit unknown id is NEVER silently re-inferred."""
    result = resolve_explicit_rubrique("99")
    assert isinstance(result, NeedsReview)
    assert result.reason is ReasonCode.UNKNOWN_RUBRIC_ID

    result = resolve_explicit_rubrique("22")
    assert result == Mapped(RubriqueId("22"))


def test_colle_word_boundary_never_matches_collecteur():
    """G1 review H6: 'collecteur' must not classify as glue."""
    assert classify_colle("collecteur d'echappement") is None
    assert classify_colle("piece recollee") is None


def test_rubrique_9_montant_total_not_line_assignable():
    """G1 review M3: the aggregate MONTANT TOTAL row is never a line target."""
    result = resolve_explicit_rubrique("9")
    assert isinstance(result, NeedsReview)
    assert result.reason is ReasonCode.UNKNOWN_RUBRIC_ID


def test_peinture_materials_map_to_16_bare_peinture_insufficient():
    """Spec-compliance gap (DOMAIN_MODEL §3): materials/ingredients -> 16;
    a bare 'peinture' stays insufficient."""
    from mcma.domain.rubriques import classify_peinture_materials

    assert classify_peinture_materials("produit de peinture") == RubriqueId("16")
    assert classify_peinture_materials("peintures et ingredients") == RubriqueId("16")
    assert classify_peinture_materials("ingredients") == RubriqueId("16")
    assert classify_peinture_materials("peinture") is None
    assert classify_peinture_materials("aile avant") is None
