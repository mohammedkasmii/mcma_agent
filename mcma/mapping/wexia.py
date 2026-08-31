"""
mcma.mapping.wexia — typed Wexia input boundary (ADR-0002, DOMAIN_MODEL §3).

Structured fields (`item_type`, `operation_type`, `labor_type_id`) come first;
free text never overrides them. This module only parses/normalizes into typed
structures — classification rules live in mcma.domain, plan building in
mcma.planning (which consumes this model structurally, without importing it).
"""

from decimal import Decimal, InvalidOperation
from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from mcma.domain.enums import LabourFamily
from mcma.domain.normalize import normalize_text

def _to_decimal(value: Any) -> Decimal:
    if value is None or value == "":
        return Decimal("0")
    try:
        dec = Decimal(str(value))
        if not dec.is_finite():
            raise ValueError(f"not a finite decimal: {value!r}")
        return dec
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"not a decimal amount: {value!r}") from exc


def _to_optional_decimal(value: Any) -> Optional[Decimal]:
    """Chiffrage totals: absent/empty is MISSING (None), never silently zero
    (G1 review H3). An explicit '0' stays a legitimate zero."""
    if value is None or value == "":
        return None
    return _to_decimal(value)


class _Base(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)


def _null_to_empty_string(v):
    """Correction batch (private dossier validation finding): a JSON
    `null` in a text field is a common encoding of "absent", not a type
    error -- normalized to "" here so a real dossier's `notes: null`
    doesn't reject the ENTIRE dossier at the typed boundary. This is a
    general robustness fix (null-vs-absent is unrelated to any specific
    dossier's content) -- the redacted validation-error report that
    surfaced it named only the field PATH and error TYPE, never a value."""
    return "" if v is None else v


class WexiaPieceLine(_Base):
    item_type: str = "part"
    item_name: str = ""
    part_type: Optional[str] = None
    is_original: Optional[bool] = None
    mcma_rubric_id: Optional[str] = None
    operation_type: Optional[str] = None
    labor_type_id: Optional[str] = None
    # Real dossiers carry the operation here ("remplacement"/"reparation")
    # while operation_type is null. extra="ignore" was discarding it, so
    # glass lines that state their operation plainly still came out
    # AMBIGUOUS_GLASS. Kept as raw text: it is evidence, not a decision.
    repair_action: Optional[str] = None
    notes: str = ""
    subtotal: Decimal = Decimal("0")
    depreciation_amount: Decimal = Decimal("0")

    @field_validator("subtotal", "depreciation_amount", mode="before")
    @classmethod
    def _decimals(cls, v):
        return _to_decimal(v)

    @field_validator("notes", mode="before")
    @classmethod
    def _notes_null_to_empty(cls, v):
        return _null_to_empty_string(v)

    @property
    def is_labour(self) -> bool:
        return (
            normalize_text(self.item_type) in ("labor", "labour")
            or self.labor_type_id is not None
        )


class WexiaMoLine(_Base):
    operation_type: Optional[str] = None
    labor_type_id: Optional[str] = None
    # Real dossiers carry the operation here ("remplacement"/"reparation")
    # while operation_type is null. extra="ignore" was discarding it, so
    # glass lines that state their operation plainly still came out
    # AMBIGUOUS_GLASS. Kept as raw text: it is evidence, not a decision.
    repair_action: Optional[str] = None
    notes: str = ""
    subtotal: Decimal = Decimal("0")

    @field_validator("notes", mode="before")
    @classmethod
    def _notes_null_to_empty(cls, v):
        return _null_to_empty_string(v)

    @field_validator("subtotal", mode="before")
    @classmethod
    def _decimals(cls, v):
        return _to_decimal(v)


class WexiaChiffrage(_Base):
    id: Optional[str] = None
    status: Optional[str] = None
    is_final: Optional[bool] = None
    scenario_type: Optional[str] = None
    estimated_days: Optional[int] = None
    total_cost: Optional[Decimal] = None
    tax_amount: Optional[Decimal] = None
    final_cost: Optional[Decimal] = None
    # The detailed HT breakdown. Stronger evidence of HT than the
    # ambiguously named total_cost, because every real sample satisfies
    # line sum == total_parts_cost + total_labor_cost while total_cost
    # means HT in some payloads and TTC in others. Missing stays None:
    # absence is not zero.
    total_parts_cost: Optional[Decimal] = None
    total_labor_cost: Optional[Decimal] = None
    # Explicit archival marker. archive_cycle is modelled for fidelity but
    # is NOT proof of archival on its own -- archived_at is the marker
    # that says a version was retired.
    archived_at: Optional[str] = None
    archive_cycle: Optional[int] = None
    lignes_pieces: List[WexiaPieceLine] = Field(default_factory=list)
    lignes_mo: List[WexiaMoLine] = Field(default_factory=list)

    @field_validator(
        "total_cost", "tax_amount", "final_cost",
        "total_parts_cost", "total_labor_cost",
        mode="before",
    )
    @classmethod
    def _decimals(cls, v):
        return _to_optional_decimal(v)

    @property
    def has_lines(self) -> bool:
        return bool(self.lignes_pieces or self.lignes_mo)


class WexiaDossier(_Base):
    reference_number: Optional[str] = None
    claim_number: Optional[str] = None
    license_plate: Optional[str] = None
    id_sinistre: Optional[str] = None
    mission_type: Optional[str] = None
    repair_mode: Optional[str] = None
    incident_description: Optional[str] = None
    # None = marker absent from the payload; the builder fails closed on it
    # (G1 review H4 — the exclusion flag must never default to permissive).
    is_reform: Optional[bool] = None
    # Correction batch (section J, non-table header fields) — fallbacks
    # only; the vehicule-level/chiffrage-level/observations_expert-level
    # values are preferred where both exist (docs/recovery/PORTAL_CONTRACT.md
    # §5, recovered baseline mapper/wexia_mapper.py:383,393,454,443-444).
    mileage_km: Optional[int] = None
    market_value: Optional[int] = None
    responsibility_rate: Optional[int] = None
    expert_observations: Optional[str] = None


class WexiaVehicule(_Base):
    license_plate: Optional[str] = None
    mileage_km: Optional[int] = None
    market_value: Optional[int] = None


class WexiaObservationsExpert(_Base):
    """Correction batch (section J): the CONFIRMED source of
    #ObservationMission is observations_expert.texte, NOT
    dossier.incident_description -- those are distinct fields in the raw
    Wexia payload (recovered baseline mapper/wexia_mapper.py:442-445), and
    incident_description is used elsewhere only as an internal mode-
    detection signal (mcma.planning.plan._detect_mode_fail_closed), never
    as form-field content."""

    texte: Optional[str] = None


class WexiaAssureur(_Base):
    responsibility_rate: Optional[int] = None


class WexiaInput(_Base):
    dossier: WexiaDossier = Field(default_factory=WexiaDossier)
    vehicule: WexiaVehicule = Field(default_factory=WexiaVehicule)
    chiffrages: List[WexiaChiffrage] = Field(default_factory=list)
    observations_expert: WexiaObservationsExpert = Field(default_factory=WexiaObservationsExpert)
    assureur: WexiaAssureur = Field(default_factory=WexiaAssureur)

    @property
    def registration_raw(self) -> Optional[str]:
        return self.vehicule.license_plate or self.dossier.license_plate or None

    @property
    def primary_reference(self) -> Optional[str]:
        return self.dossier.reference_number or self.dossier.claim_number or None

    @property
    def id_sinistre_raw(self) -> Optional[str]:
        return self.dossier.id_sinistre or None


def parse_wexia(raw: dict) -> WexiaInput:
    """Typed boundary: unknown keys are ignored, amounts become Decimal (a
    malformed amount raises — fail closed), nothing is inferred here."""
    return WexiaInput.model_validate(raw)
