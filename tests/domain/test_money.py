"""INC-04 — Money (Decimal, 2dp, ROUND_HALF_UP) and fail-closed tax allocation."""

from decimal import Decimal

import pytest

from mcma.core.money import InvalidTaxAllocationError, Money, allocate_tax
from mcma.domain.results import NeedsReview, ReasonCode, tva_allocation_result


def test_money_is_decimal_half_up():
    assert Money.of("10.005").amount == Decimal("10.01")
    assert Money.of("10.004").amount == Decimal("10.00")
    assert Money.of(3).amount == Decimal("3.00")
    assert Money.of(Decimal("1.2")).amount == Decimal("1.20")
    total = Money.of("0.10") + Money.of("0.20")
    assert total == Money.of("0.30")  # no float drift, ever
    assert (Money.of("5.00") - Money.of("2.50")).amount == Decimal("2.50")


def test_money_rejects_float_and_negative_constructor_allows_sign():
    with pytest.raises(TypeError):
        Money.of(0.1)  # float never crosses a domain boundary
    assert Money.of("-1.00").is_negative


def test_money_ratio_multiplication_quantizes():
    assert Money.of("100.00").times(Decimal("0.20")) == Money.of("20.00")
    assert Money.of("0.03").times(Decimal("0.20")) == Money.of("0.01")  # HALF_UP


def test_tax_remainder_allocation_sums_to_0_01():
    lines = [Money.of("1200.00"), Money.of("300.00"), Money.of("500.00")]
    total_tva = Money.of("400.00")
    allocated = allocate_tax(lines, total_tva, rate=Decimal("0.20"))
    assert sum((m.amount for m in allocated), Decimal("0")) == total_tva.amount
    assert allocated == [Money.of("240.00"), Money.of("60.00"), Money.of("100.00")]

    # An awkward total still lands exactly, remainder on the last line.
    lines = [Money.of("0.01"), Money.of("0.01"), Money.of("0.01")]
    total_tva = Money.of("0.01")
    allocated = allocate_tax(lines, total_tva, rate=Decimal("0.20"))
    assert sum((m.amount for m in allocated), Decimal("0")) == Decimal("0.01")


def test_negative_line_tva_fails_closed():
    """B.6: no clamp, no redistribution — a negative allocated line raises in
    core and surfaces as NeedsReview(INVALID_TAX_ALLOCATION) in the domain."""
    lines = [Money.of("100.00"), Money.of("1.00")]
    # 20% of 100.00 = 20.00 already exceeds the 5.00 total: last line would go
    # negative (5.00 - 20.00 = -15.00).
    with pytest.raises(InvalidTaxAllocationError):
        allocate_tax(lines, Money.of("5.00"), rate=Decimal("0.20"))

    result = tva_allocation_result(lines, Money.of("5.00"))
    assert isinstance(result, NeedsReview)
    assert result.reason is ReasonCode.INVALID_TAX_ALLOCATION


def test_tax_allocation_zero_total_gives_zero_lines():
    lines = [Money.of("10.00"), Money.of("20.00")]
    allocated = allocate_tax(lines, Money.ZERO, rate=Decimal("0.20"))
    assert allocated == [Money.ZERO, Money.ZERO]


def test_money_rejects_non_finite_values():
    """G1 review M1: NaN/Infinity must never construct a Money."""
    for bad in ("NaN", "Infinity", "-Infinity", "sNaN"):
        with pytest.raises(ValueError):
            Money.of(bad)


def test_allocation_enforces_last_line_remainder_bound():
    """G1 review H5: the last line absorbs at most 0.01 MAD beyond its own
    quantized share — an implausible remainder fails closed."""
    with pytest.raises(InvalidTaxAllocationError):
        allocate_tax([Money.of("100.00")], Money.of("500.00"))
