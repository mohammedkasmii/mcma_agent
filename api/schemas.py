"""
api/schemas.py — Request Models
================================
Pydantic models for every write endpoint.
"""

from typing import Any, Dict, Optional

from pydantic import BaseModel


class EmployeeActionUpdate(BaseModel):
    """A claim's work status and note, attributed to an employee."""
    claim_id: int
    status: str
    note: Optional[str] = ""
    updated_by: Optional[str] = None


class FillDossierRequest(BaseModel):
    payload: Dict[str, Any]


class WexiaDossierRequest(BaseModel):
    wexia_payload: Dict[str, Any]
    explicit_chiffrage_id: Optional[str] = None
