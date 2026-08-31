"""
mcma.domain.values — immutable value objects (DOMAIN_MODEL §1).
The normalized registration plate is the comparison key.
"""

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Tuple

from mcma.domain.enums import FormFieldSelector, RepairWorkflow


def _require_non_blank(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


@dataclass(frozen=True)
class RegistrationPlate:
    raw: str
    normalized: str = field(init=False, compare=True)

    def __post_init__(self):
        _require_non_blank(self.raw, "RegistrationPlate")
        nfkd = unicodedata.normalize("NFKD", self.raw)
        stripped = "".join(c for c in nfkd if not unicodedata.combining(c))
        # Keep ALL letters/digits (Arabic series letters included — dropping
        # them would collide distinct plates); remove only separators.
        normalized = re.sub(r"[\W_]", "", stripped).upper()
        if not normalized:
            raise ValueError("RegistrationPlate normalizes to empty")
        object.__setattr__(self, "normalized", normalized)

    def __eq__(self, other):
        return isinstance(other, RegistrationPlate) and self.normalized == other.normalized

    def __hash__(self):
        return hash(self.normalized)


@dataclass(frozen=True)
class InsurerReference:
    value: str

    def __post_init__(self):
        _require_non_blank(self.value, "InsurerReference")


@dataclass(frozen=True)
class IdSinistre:
    value: str

    def __post_init__(self):
        _require_non_blank(self.value, "IdSinistre")


@dataclass(frozen=True)
class AccountId:
    value: str

    def __post_init__(self):
        _require_non_blank(self.value, "AccountId")


@dataclass(frozen=True)
class RubriqueId:
    value: str

    def __post_init__(self):
        _require_non_blank(self.value, "RubriqueId")


@dataclass(frozen=True)
class FormFieldIntent:
    """One non-table header-field write (correction batch, section J;
    moved here from mcma.planning.plan by the pilot-integration
    correction so mcma.portal.writer can consume it too, without
    violating "persistence/portal may import only domain and core" --
    mcma.planning.plan re-exports this name for backward compatibility).
    `selector` is drawn from the FIXED FormFieldSelector enum -- never a
    caller-supplied string, so a plan can never name an arbitrary DOM id.
    Bound to AuthorizedExecution exactly like RowOp: it is plan data,
    consumed only inside a VerifiedMissionWriter reachable solely through
    the authorized EXECUTE path (mcma.execution.jobs.run_execute_write).
    Never a charge-mutuelle/sociétaire or final-action field (structurally
    impossible: FormFieldSelector's fixed member list contains neither)."""

    selector: FormFieldSelector
    value: str
    applicable_workflows: Tuple[RepairWorkflow, ...]

    def __post_init__(self):
        if not isinstance(self.selector, FormFieldSelector):
            raise TypeError("FormFieldIntent.selector must be a FormFieldSelector")
        if not isinstance(self.value, str) or not self.value:
            raise ValueError("FormFieldIntent.value must be a non-empty string")
        if not self.applicable_workflows:
            raise ValueError("FormFieldIntent requires at least one applicable workflow")
