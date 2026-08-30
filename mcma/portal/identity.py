"""
mcma.portal.identity -- the two-tier mission identity gate (INC-09A,
SAFETY_MODEL.md §4, BUSINESS_RULES.md B.5, ADR-0003).

`ExpectedIdentity` here is a PORTAL-LOCAL type, deliberately not imported
from mcma.planning.plan: the import-linter contract "persistence/portal may
import only domain and core" (pyproject.toml) forbids mcma.portal from
importing mcma.planning at all. Pairing a planning-level
ProposedPlan.expected_identity with this portal-level type is
mcma.execution's job -- the same "pairing lives in execution" principle
MODULE_BOUNDARIES.md §4 already establishes for AuthorizedExecution. This
type deliberately mirrors mcma.planning.plan.ExpectedIdentity's shape and
validation exactly (registration mandatory; at least one of
insurer_reference/id_sinistre required) so the translation in execution is
a straight field copy, not a remapping.

Positive agreement is required for every identifier `ExpectedIdentity`
actually supplies. An observed field that could not be read (None) is
ALWAYS a mismatch against a supplied expected field -- it is never treated
as agreement, even when the expected field is also unset elsewhere in the
comparison (no match-by-absence, footgun A4). Registration (tier 2) is
mandatory and always checked; `ExpectedIdentity`'s own constructor already
guarantees at least one tier-1 field (insurer_reference and/or id_sinistre)
is supplied, so at least one tier-1 branch below always executes.

`insurer_reference` scraping is NOT implemented in INC-09A: no confirmed
selector maps a portal field to InsurerReference specifically (PORTAL_
CONTRACT.md §3's `#ReferenceDossier` is recovered evidence for a "dossier
reference" field, not confirmed as the insurer reference domain concept).
`observe_identity()` (mcma.portal.mission) therefore always returns
`insurer_reference=None`. This is intentional and fails closed, not
silently ignored: a plan whose ExpectedIdentity relies solely on
insurer_reference (no id_sinistre) will always raise IdentityMismatch
against a real page until a confirmed selector is added -- a genuine G5-
style confirmation gap, not a bug. id_sinistre (`#IdSinistre__I`, already
present in the INC-06 mock) and registration (`#MatriculeVeh`, added in
this increment) are both scraped and fully verified.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from mcma.domain.values import IdSinistre, InsurerReference, RegistrationPlate


@dataclass(frozen=True)
class ExpectedIdentity:
    """Portal-local mirror of mcma.planning.plan.ExpectedIdentity's shape
    and validation (see module docstring for why this isn't an import)."""

    registration: RegistrationPlate
    insurer_reference: Optional[InsurerReference] = None
    id_sinistre: Optional[IdSinistre] = None

    def __post_init__(self) -> None:
        if not isinstance(self.registration, RegistrationPlate):
            raise TypeError("ExpectedIdentity requires a RegistrationPlate")
        if self.insurer_reference is not None and not isinstance(
            self.insurer_reference, InsurerReference
        ):
            raise TypeError("ExpectedIdentity.insurer_reference must be an InsurerReference")
        if self.id_sinistre is not None and not isinstance(self.id_sinistre, IdSinistre):
            raise TypeError("ExpectedIdentity.id_sinistre must be an IdSinistre")
        if self.insurer_reference is None and self.id_sinistre is None:
            raise ValueError(
                "ExpectedIdentity requires at least one of insurer_reference/id_sinistre "
                "(a registration plate alone is insufficient)"
            )


@dataclass(frozen=True)
class ObservedIdentity:
    """Identifiers scraped from the currently opened mission page. A field
    that could not be read (missing/empty on the page) is None -- never
    guessed, never defaulted to the expected value."""

    registration: Optional[RegistrationPlate]
    insurer_reference: Optional[InsurerReference]
    id_sinistre: Optional[IdSinistre]


class IdentityMismatch(Exception):
    """Raised on any identity disagreement, or a missing observed value for
    a field the plan supplies. Fail-closed: no write path is ever reachable
    without this succeeding."""

    def __init__(self, field: str):
        super().__init__(f"identity mismatch on {field}")
        self.field = field


def verify_identity(expected: ExpectedIdentity, observed: ObservedIdentity) -> None:
    if observed.registration is None or observed.registration != expected.registration:
        raise IdentityMismatch("registration")
    if expected.insurer_reference is not None:
        if (
            observed.insurer_reference is None
            or observed.insurer_reference != expected.insurer_reference
        ):
            raise IdentityMismatch("insurer_reference")
    if expected.id_sinistre is not None:
        if observed.id_sinistre is None or observed.id_sinistre != expected.id_sinistre:
            raise IdentityMismatch("id_sinistre")
