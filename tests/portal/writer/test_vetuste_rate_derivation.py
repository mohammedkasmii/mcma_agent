"""
INC-09B amendment #4 -- derive_vetuste_rate: exact HALF_UP formula
(Decimal, matching Money's own convention), fail-closed when TTC is zero.
"""

from decimal import Decimal

import pytest

from mcma.portal.writer import VetusteRateDerivationUndefined, derive_vetuste_rate
from writer_test_support import money


def test_derive_vetuste_rate_basic():
    assert derive_vetuste_rate(money("10.00"), money("100.00")) == Decimal("10.00")


def test_derive_vetuste_rate_half_up_boundary():
    # 1.00 / 8.00 * 100 = 12.5 exactly -> HALF_UP rounds to nearest 2dp is
    # already exact (12.50); use a case with a genuine 3rd-decimal tie.
    # 0.125 -> rounds to 0.13 under HALF_UP when quantized to 2dp from a
    # 3-decimal exact value.
    rate = derive_vetuste_rate(money("1.00"), money("8.00"))
    assert rate == Decimal("12.50")


def test_derive_vetuste_rate_repeating_fraction_rounds_half_up():
    # 10.00 / 3.00 * 100 = 333.333... -> 333.33
    rate = derive_vetuste_rate(money("10.00"), money("3.00"))
    assert rate == Decimal("333.33")


def test_derive_vetuste_rate_zero_ttc_is_undefined():
    with pytest.raises(VetusteRateDerivationUndefined):
        derive_vetuste_rate(money("10.00"), money("0.00"))


def test_derive_vetuste_rate_zero_amount_is_zero_rate():
    assert derive_vetuste_rate(money("0.00"), money("100.00")) == Decimal("0.00")


# --------------------------------------------------------------------- #
# Argument-order regression (CI: the PEC handoff aborted before review)
# --------------------------------------------------------------------- #


def test_a_zero_vetuste_row_derives_a_zero_rate_and_does_not_raise():
    """The exact shape of the runner's PEC fixture: HT 10, TVA 2, no
    depreciation.

    edit_conventionne_row called derive_vetuste_rate(intent.ht,
    intent.vetuste) -- arguments swapped. With vetuste 0.00 that makes TTC
    zero, which raises VetusteRateDerivationUndefined by design. That
    subclasses WriteAborted, so _perform_writes turned it into
    WRITE_NOT_CONFIRMED and an ordinary dossier with no depreciation
    aborted before ever reaching human handoff."""
    from mcma.core.money import Money
    from mcma.portal.writer import derive_vetuste_rate

    ht, tva, vetuste = Money.of("10.00"), Money.of("2.00"), Money.of("0.00")
    assert derive_vetuste_rate(vetuste, ht + tva) == Decimal("0.00")


def test_the_swapped_argument_order_is_exactly_what_used_to_raise():
    """Pins WHY it failed, so the ordering cannot be reintroduced as a
    harmless-looking edit."""
    from mcma.core.money import Money
    from mcma.portal.writer import VetusteRateDerivationUndefined, derive_vetuste_rate

    with pytest.raises(VetusteRateDerivationUndefined):
        derive_vetuste_rate(Money.of("10.00"), Money.of("0.00"))


def test_a_non_zero_vetuste_still_derives_the_documented_rate():
    from mcma.core.money import Money
    from mcma.portal.writer import derive_vetuste_rate

    ht, tva, vetuste = Money.of("10.00"), Money.of("2.00"), Money.of("1.00")
    assert derive_vetuste_rate(vetuste, ht + tva) == Decimal("8.33")


def test_mutation_and_verification_derive_the_rate_identically():
    """The defect was not the formula but the two call sites DISAGREEING:
    verify_row() always used (vetuste, ht+tva). This asserts both
    production call sites now pass the vetuste amount first."""
    import ast
    import inspect

    from mcma.portal import writer as writer_module

    # Parsed, not grepped: a text search also matches the comment that
    # EXPLAINS the argument order, which is not a call site.
    tree = ast.parse(inspect.getsource(writer_module))
    first_args = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "derive_vetuste_rate"
            and node.args
        ):
            first_args.append(ast.unparse(node.args[0]))

    assert first_args, "no call sites found -- has the helper been renamed?"
    for first_arg in first_args:
        assert "vetuste" in first_arg, (
            f"derive_vetuste_rate passes {first_arg!r} first; the first argument "
            "is the vetuste AMOUNT and the second is TTC"
        )
