"""
mcma.domain.results — mapping result algebra (DOMAIN_MODEL §4):
MapResult = Mapped(value) | NeedsReview(reason_code). Fail-closed everywhere.
"""

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum, unique
from typing import Any, Sequence, Union

from mcma.core.money import InvalidTaxAllocationError, Money, allocate_tax


@unique
class ReasonCode(Enum):
    INVALID_TAX_ALLOCATION = "INVALID_TAX_ALLOCATION"
    AMBIGUOUS_GLASS = "AMBIGUOUS_GLASS"
    UNKNOWN_RUBRIC_ID = "UNKNOWN_RUBRIC_ID"
    UNKNOWN_LABOUR = "UNKNOWN_LABOUR"
    CONTRADICTORY_LABOUR = "CONTRADICTORY_LABOUR"
    UNKNOWN_PART_ORIGIN = "UNKNOWN_PART_ORIGIN"


@dataclass(frozen=True)
class Mapped:
    value: Any


@dataclass(frozen=True)
class NeedsReview:
    reason: ReasonCode
    detail: str = ""


MapResult = Union[Mapped, NeedsReview]


def tva_allocation_result(
    lines: Sequence[Money], total_tva: Money, rate: Decimal = Decimal("0.20")
) -> MapResult:
    """Domain-facing allocation: Mapped(list[Money]) or the fail-closed
    NeedsReview(INVALID_TAX_ALLOCATION) sentinel (B.6)."""
    try:
        return Mapped(allocate_tax(lines, total_tva, rate=rate))
    except InvalidTaxAllocationError as exc:
        return NeedsReview(ReasonCode.INVALID_TAX_ALLOCATION, detail=str(exc))
