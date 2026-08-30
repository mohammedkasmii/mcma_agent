"""INC-04 — glass mapping (B.2): component identity x operation -> 19-24;
requires BOTH; ambiguity/conflict fails closed; part_type never involved."""

import inspect

import pytest

from mcma.domain.enums import GlassComponent, GlassOperation
from mcma.domain.results import Mapped, NeedsReview, ReasonCode
from mcma.domain.rubriques import classify_glass_line, detect_glass_component, glass_rubrique
from mcma.domain.values import RubriqueId

MATRIX = {
    (GlassComponent.VITRE, GlassOperation.REPARATION): "19",
    (GlassComponent.VITRE, GlassOperation.REMPLACEMENT): "20",
    (GlassComponent.PARE_BRISE, GlassOperation.REPARATION): "21",
    (GlassComponent.PARE_BRISE, GlassOperation.REMPLACEMENT): "22",
    (GlassComponent.LUNETTE_ARRIERE, GlassOperation.REPARATION): "23",
    (GlassComponent.LUNETTE_ARRIERE, GlassOperation.REMPLACEMENT): "24",
}


def test_glass_matrix_complete():
    for (component, operation), rubrique in MATRIX.items():
        assert glass_rubrique(component, operation) == RubriqueId(rubrique)


def test_glass_line_classification_from_vocabulary():
    assert classify_glass_line("Pare-brise avant", "remplacement") == Mapped(RubriqueId("22"))
    assert classify_glass_line("réparation impact pare-brise", None) == Mapped(RubriqueId("21"))
    assert classify_glass_line("Lunette arrière", "remplacement") == Mapped(RubriqueId("24"))
    assert classify_glass_line("vitre porte avant", "résine") == Mapped(RubriqueId("19"))
    assert classify_glass_line("glace latérale", "pose") == Mapped(RubriqueId("20"))


def test_glass_requires_component_and_operation():
    result = classify_glass_line("Pare-brise avant", None)  # no operation signal
    assert isinstance(result, NeedsReview)
    assert result.reason is ReasonCode.AMBIGUOUS_GLASS


def test_ambiguous_or_conflicting_glass_fails_closed():
    # Conflicting operation signals
    result = classify_glass_line("pare-brise réparation et remplacement", None)
    assert isinstance(result, NeedsReview)
    assert result.reason is ReasonCode.AMBIGUOUS_GLASS
    # Ambiguous component (two distinct glass components named)
    result = classify_glass_line("vitre et lunette arrière", "remplacement")
    assert isinstance(result, NeedsReview)
    assert result.reason is ReasonCode.AMBIGUOUS_GLASS


def test_part_type_never_used_for_glass_family():
    """Structural: glass classification never sees part_type (origin-only,
    B.1/B.2); and a glass line with any part_type input simply has none to give."""
    params = set(inspect.signature(classify_glass_line).parameters)
    assert "part_type" not in params
    params = set(inspect.signature(glass_rubrique).parameters)
    assert "part_type" not in params


def test_detect_glass_component_vocabulary():
    assert detect_glass_component("pare brise") is GlassComponent.PARE_BRISE
    assert detect_glass_component("parebrise") is GlassComponent.PARE_BRISE
    assert detect_glass_component("déflecteur") is GlassComponent.VITRE
    assert detect_glass_component("lunette ar") is GlassComponent.LUNETTE_ARRIERE
    assert detect_glass_component("aile avant") is None


def test_glass_never_lands_in_rubrique_1():
    """The corrected rule can never fold glass into rubrique 1 (F13 fixed in
    the new domain): every classification outcome is 19-24 or NeedsReview."""
    outcomes = [
        classify_glass_line(desc, op)
        for desc in ("pare-brise", "vitre", "lunette arrière", "glace")
        for op in (None, "remplacement", "réparation", "réparation remplacement")
    ]
    for outcome in outcomes:
        if isinstance(outcome, Mapped):
            assert outcome.value.value in {"19", "20", "21", "22", "23", "24"}
        else:
            assert isinstance(outcome, NeedsReview)


def test_depose_and_repose_are_not_remplacement():
    """G1 review H7: removal verbs must not substring-match 'pose'."""
    result = classify_glass_line("pare-brise", "depose")
    assert isinstance(result, NeedsReview)
    result = classify_glass_line("repose vitre", None)
    assert isinstance(result, NeedsReview)
