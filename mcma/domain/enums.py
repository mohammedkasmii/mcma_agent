"""mcma.domain.enums — normalization targets (DOMAIN_MODEL §2). Never
stringly-typed (footgun A12)."""

from enum import Enum, unique


@unique
class Origin(Enum):
    ORIGINAL = "ORIGINAL"
    ADAPTABLE = "ADAPTABLE"
    RECOVERED = "RECOVERED"


@unique
class LabourFamily(Enum):
    TOLERIE_CARROSSERIE = "TOLERIE_CARROSSERIE"
    MECANIQUE = "MECANIQUE"
    PEINTURE = "PEINTURE"
    ELECTRIQUE = "ELECTRIQUE"
    MARBRE = "MARBRE"
    PARALLELISME_EQUILIBRAGE = "PARALLELISME_EQUILIBRAGE"


@unique
class GlassComponent(Enum):
    VITRE = "VITRE"
    PARE_BRISE = "PARE_BRISE"
    LUNETTE_ARRIERE = "LUNETTE_ARRIERE"


@unique
class GlassOperation(Enum):
    REPARATION = "REPARATION"
    REMPLACEMENT = "REMPLACEMENT"


@unique
class Permission(Enum):
    NOTIFICATIONS_READ = "notifications:read"
    NOTIFICATIONS_UPDATE = "notifications:update"
    JOBS_PLAN = "jobs:plan"
    JOBS_EXECUTE = "jobs:execute"
    JOBS_VIEW = "jobs:view"
    SESSIONS_MANAGE = "sessions:manage"
    ACCOUNTS_MANAGE = "accounts:manage"
    USERS_MANAGE = "users:manage"
