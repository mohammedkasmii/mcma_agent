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


class WexiaPieceLine(_Base):
    item_type: str = "part"
    item_name: str = ""
    part_type: Optional[str] = None
    is_original: Optional[bool] = None
    mcma_rubric_id: Optional[str] = None
    operation_type: Optional[str] = None
    labor_type_id: Optional[str] = None
    notes: str = ""
    subtotal: Decimal = Decimal("0")
    depreciation_amount: Decimal = Decimal("0")

    @field_validator("subtotal", "depreciation_amount", mode="before")
    @classmethod
    def _decimals(cls, v):
        return _to_decimal(v)

    @property
    def is_labour(self) -> bool:
        return (
            normalize_text(self.item_type) in ("labor", "labour")
            or self.labor_type_id is not None
        )


class WexiaMoLine(_Base):
    operation_type: Optional[str] = None
    labor_type_id: Optional[str] = None
    notes: str = ""
    subtotal: Decimal = Decimal("0")

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
    lignes_pieces: List[WexiaPieceLine] = Field(default_factory=list)
    lignes_mo: List[WexiaMoLine] = Field(default_factory=list)

    @field_validator("total_cost", "tax_amount", "final_cost", mode="before")
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


class WexiaVehicule(_Base):
    license_plate: Optional[str] = None


class WexiaInput(_Base):
    dossier: WexiaDossier = Field(default_factory=WexiaDossier)
    vehicule: WexiaVehicule = Field(default_factory=WexiaVehicule)
    chiffrages: List[WexiaChiffrage] = Field(default_factory=list)

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
