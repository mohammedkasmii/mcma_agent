"""
mcma.domain.portal_accounts -- typed classification of the four shared
PortalAccount profiles (owner amendment, correction batch).

Login topology (owner amendment): the shared SinAuto site's landing page
offers two provider icons (MCMA / MAMDA); the chosen provider leads to a
login where a human enters SHARED credentials and completes OTP; the
credential profile itself then determines whether the authenticated
account is Oujda or Nador. `entity` (DATA_MODEL.md's accounts.entity
column) is that PRE-LOGIN provider choice; `scope` (accounts.scope) is
the POST-LOGIN credential/account assignment. There are exactly four
profiles -- MCMA+Oujda, MCMA+Nador, MAMDA+Oujda, MAMDA+Nador -- and they
are never modeled per employee (mcma.persistence's UNIQUE(entity, scope)
index is the durable guarantee; this module is the typed-application-
layer mirror of that same invariant).

The database deliberately does NOT CHECK-constrain `scope` to a closed
set (a future office must remain addable by a plain data migration, never
a schema change) -- this module instead owns the CURRENT canonical set
the application recognizes. An unrecognized entity/scope pairing fails
closed (ValueError) rather than being silently treated as a known,
handled profile.
"""

from dataclasses import dataclass
from enum import Enum, unique


@unique
class PortalEntity(Enum):
    """The pre-login provider choice on the shared SinAuto landing page."""

    MCMA = "MCMA"
    MAMDA = "MAMDA"


@unique
class PortalScope(Enum):
    """The post-login credential/account assignment."""

    OUJDA = "OUJDA"
    NADOR = "NADOR"


@dataclass(frozen=True)
class PortalAccountProfile:
    """One of the four shared PortalAccount profiles. Carries no
    account_id, credentials, or session material -- purely the typed
    (entity, scope) classification."""

    entity: PortalEntity
    scope: PortalScope

    @property
    def is_mcma(self) -> bool:
        """MAMDA is notification-only (SAFETY_MODEL.md correction batch):
        only an MCMA profile may ever back a form-filling/write job."""
        return self.entity is PortalEntity.MCMA

    @classmethod
    def from_row(cls, entity: str, scope: str) -> "PortalAccountProfile":
        """Classifies a raw accounts.entity/accounts.scope pair. Fails
        closed on anything not in the current canonical set -- never
        guesses which of the four profiles an unrecognized value might
        mean."""
        try:
            entity_value = PortalEntity(entity)
        except ValueError as exc:
            raise ValueError(f"unrecognized portal account entity: {entity!r}") from exc
        try:
            scope_value = PortalScope(scope)
        except ValueError as exc:
            raise ValueError(f"unrecognized portal account scope: {scope!r}") from exc
        return cls(entity_value, scope_value)


THE_FOUR_PROFILES: tuple[PortalAccountProfile, ...] = tuple(
    PortalAccountProfile(entity, scope) for entity in PortalEntity for scope in PortalScope
)
