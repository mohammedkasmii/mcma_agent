"""
mcma.core.money — Money value object (Decimal, 2 dp, ROUND_HALF_UP) and the
deterministic tax remainder allocation (BUSINESS_RULES B.6, DOMAIN_MODEL §5).

No float ever crosses a domain boundary; constructing Money from float is a
TypeError. Negative allocation lines are never clamped or redistributed —
allocation fails closed with InvalidTaxAllocationError.
"""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import ClassVar, Sequence, Union

_CENT = Decimal("0.01")


class InvalidTaxAllocationError(ValueError):
    """Raised when the deterministic allocation would produce a negative line
    (B.6: no clamp, no redistribution — fail closed)."""


@dataclass(frozen=True, order=True)
class Money:
    amount: Decimal

    ZERO: ClassVar["Money"]

    def __post_init__(self):
        if not isinstance(self.amount, Decimal):
            raise TypeError("Money.amount must be a Decimal; use Money.of()")
        if not self.amount.is_finite():
            raise ValueError(f"Money must be finite, got {self.amount}")
        object.__setattr__(self, "amount", self.amount.quantize(_CENT, rounding=ROUND_HALF_UP))

    @classmethod
    def of(cls, value: Union[str, int, Decimal]) -> "Money":
        if isinstance(value, float):
            raise TypeError("Money never accepts float; pass str, int, or Decimal")
        if isinstance(value, Money):
            return value
        try:
            return cls(Decimal(str(value)))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"not a monetary value: {value!r}") from exc

    @property
    def is_negative(self) -> bool:
        return self.amount < 0

    def times(self, ratio: Decimal) -> "Money":
        if not isinstance(ratio, Decimal):
            raise TypeError("ratio must be a Decimal")
        return Money(self.amount * ratio)

    def __add__(self, other: "Money") -> "Money":
        return Money(self.amount + other.amount)

    def __sub__(self, other: "Money") -> "Money":
        return Money(self.amount - other.amount)

    def __str__(self) -> str:
        return f"{self.amount:.2f}"


Money.ZERO = Money(Decimal("0.00"))


def allocate_tax(
    lines: Sequence[Money], total_tax: Money, rate: Decimal = Decimal("0.20")
) -> list[Money]:
    """Deterministic per-line tax allocation: every line but the last gets
    quantize(ht * rate); the last line absorbs the remainder so the sum equals
    total_tax exactly (0.01 MAD bound, no 0.05 tolerance). A negative line —
    including a negative remainder — fails closed (B.6)."""
    if not lines:
        return []
    if total_tax == Money.ZERO:
        return [Money.ZERO for _ in lines]

    allocated: list[Money] = []
    running = Money.ZERO
    for line in lines[:-1]:
        share = line.times(rate)
        allocated.append(share)
        running = running + share
    remainder = total_tax - running
    allocated.append(remainder)

    negative = [m for m in allocated if m.is_negative]
    if negative:
        raise InvalidTaxAllocationError(
            f"tax allocation produced negative line(s) {negative}; "
            "no clamp/redistribution is permitted (NEEDS_REVIEW: INVALID_TAX_ALLOCATION)"
        )
    # The last line may absorb at most 0.01 MAD beyond its own quantized
    # share — an implausible remainder means the totals are inconsistent.
    expected_last = lines[-1].times(rate)
    if abs(remainder.amount - expected_last.amount) > _CENT:
        raise InvalidTaxAllocationError(
            f"remainder {remainder} deviates from the last line's quantized "
            f"share {expected_last} by more than 0.01 MAD"
        )
    return allocated
