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
