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


@unique
class RepairWorkflow(Enum):
    MODE_NORMAL = "mode_normal"
    GARAGE_CONVENTIONNE = "garage_conventionne"


@unique
class FormFieldSelector(Enum):
    """Correction batch (owner amendment, section J) -- the FIXED,
    exhaustive allowlist of non-table header-field DOM ids a
    FormFieldIntent may name. A plan can never reference an arbitrary
    caller-supplied selector string; only these five (of the ten
    recovered in docs/recovery/PORTAL_CONTRACT.md §5) currently have
    both a confirmed single-valued JSON source AND a confirmed selector
    with no portal-computed-value ambiguity -- see mcma.planning.plan's
    module docstring for the evidence matrix and the fields deliberately
    NOT implemented here (MontantReparation/MontantTVA/MontantTTC are
    likely portal-derived; VehRepareI/TypeReforme have no confirmed JSON
    source mapping in any recovered evidence)."""

    KILOMETRAGE = "Kilometrage"
    VALEUR_VENALE = "ValeurVenale"
    VALEUR_VENALE_ESTIME = "ValeurVenaleEstime"
    NBRE_JOUR_IMMOBILISATION = "NbreJourImmobilisation"
    PART_RESPONSABILITE = "PartResponsabilite"
    OBSERVATION_MISSION = "ObservationMission"
