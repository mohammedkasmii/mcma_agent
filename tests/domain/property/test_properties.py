"""INC-04 — property-based tests (Hypothesis, bounded budget) for money,
normalization, glass, and origin invariants."""

from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from mcma.core.money import InvalidTaxAllocationError, Money, allocate_tax
from mcma.domain.enums import GlassComponent, GlassOperation
from mcma.domain.normalize import normalize_text
from mcma.domain.results import Mapped
from mcma.domain.rubriques import classify_glass_line, classify_ordinary_part, glass_rubrique

BUDGET = settings(max_examples=200, deadline=None)

money_cents = st.integers(min_value=0, max_value=10_000_000)


@BUDGET
@given(st.lists(money_cents, min_size=1, max_size=12), money_cents)
def test_tax_allocation_preserves_total_or_fails_closed(cents_list, tva_cents):
    lines = [Money.of(Decimal(c) / 100) for c in cents_list]
    total_tva = Money.of(Decimal(tva_cents) / 100)
    try:
        allocated = allocate_tax(lines, total_tva, rate=Decimal("0.20"))
    except InvalidTaxAllocationError:
        return  # fail-closed path is always acceptable
    assert sum((m.amount for m in allocated), Decimal("0")) == total_tva.amount
    assert all(not m.is_negative for m in allocated), "no negative line, ever"


@BUDGET
@given(st.text(max_size=80))
def test_normalize_idempotent_accents_punct_ws(text):
    once = normalize_text(text)
    assert normalize_text(once) == once
    assert once == " ".join(once.split())  # collapsed whitespace
    assert once == once.lower()


_COMPONENT_ALIASES = {
    GlassComponent.VITRE: ["vitre", "glace", "déflecteur"],
    GlassComponent.PARE_BRISE: ["pare-brise", "parebrise", "pare brise"],
    GlassComponent.LUNETTE_ARRIERE: ["lunette arrière", "lunette arriere", "lunette ar"],
}
_OPERATION_ALIASES = {
    GlassOperation.REPARATION: ["réparation", "reparation", "résine", "resine", "impact"],
    GlassOperation.REMPLACEMENT: ["remplacement", "pose"],
}


@BUDGET
@given(
    st.sampled_from(list(GlassComponent)),
    st.sampled_from(list(GlassOperation)),
    st.data(),
)
def test_glass_component_x_operation_property(component, operation, data):
    comp_text = data.draw(st.sampled_from(_COMPONENT_ALIASES[component]))
    op_text = data.draw(st.sampled_from(_OPERATION_ALIASES[operation]))
    result = classify_glass_line(comp_text, op_text)
    assert result == Mapped(glass_rubrique(component, operation))


@BUDGET
@given(
    st.sampled_from(
        ["original", "origine", "oem", "neuf", "neuve", "new",
         "adaptable", "equivalent", "aftermarket",
         "recuperation", "recuperable", "occasion", "used"]
    )
)
def test_ordinary_part_always_lands_in_1_2_3(part_type):
    result = classify_ordinary_part(part_type=part_type, is_original=None)
    assert isinstance(result, Mapped)
    assert result.value.value in {"1", "2", "3"}, "never 4-6/10-11/13-15 for a part"
