"""
core/utils.py — Mathematical & Text Utility Functions
======================================================
Deterministic financial precision (Decimal rounding, tax remainder allocation)
and string normalizers for vehicle license plates and textual fields.
"""

import re
import unicodedata
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Any
from core.constants import CENT


def to_decimal(val: Any) -> Decimal:
    """Safely converts input to Decimal, stripping currency notations."""
    if val is None or val == "":
        return Decimal("0.00")
    if isinstance(val, (int, float, Decimal)):
        return Decimal(str(val))
    s = str(val).strip().replace(" ", "").replace("DH", "").replace("dh", "").replace("MAD", "")
    s = s.replace(",", ".")
    try:
        return Decimal(s)
    except Exception:
        return Decimal("0.00")


def quantize_money(val: Decimal) -> Decimal:
    """Rounds Decimal to 2 decimal places using ROUND_HALF_UP."""
    return val.quantize(CENT, rounding=ROUND_HALF_UP)


def format_money(val: Any) -> str:
    """Formats monetary values to 2 decimal places string: '1234.50'."""
    d = to_decimal(val)
    return str(quantize_money(d))


def normalize_text(text: Optional[str]) -> str:
    """Normalizes text by removing accents, punctuation, and extra whitespace."""
    if not text:
        return ""
    nfkd = unicodedata.normalize('NFKD', str(text))
    ascii_text = "".join([c for c in nfkd if not unicodedata.combining(c)])
    cleaned = re.sub(r"[^a-zA-Z0-9\s]", " ", ascii_text).lower()
    return " ".join(cleaned.split())


def normalize_registration(reg: Optional[str]) -> str:
    """Normalizes vehicle registration for strict equality checks."""
    if not reg:
        return ""
    nfkd = unicodedata.normalize('NFKD', str(reg))
    ascii_text = "".join([c for c in nfkd if not unicodedata.combining(c)])
    return re.sub(r"[^a-zA-Z0-9]", "", ascii_text).upper()


def extract_search_matricule(plate: str) -> str:
    """
    Extracts the primary leading numeric block for MCMA search.
    Example: '34602-B-7' -> '34602', '05149/A/77' -> '05149'
    """
    if not plate:
        return ""
    plate_clean = str(plate).strip()
    match = re.search(r"\d+", plate_clean)
    if match:
        return match.group(0)
    return plate_clean


def format_date_dd_mm_yyyy(date_str: Optional[str]) -> Optional[str]:
    """Converts ISO or standard date formats to DD/MM/YYYY."""
    if not date_str or not str(date_str).strip():
        return None
    raw = str(date_str).strip().split("T")[0].split(" ")[0]
    parts_dash = raw.split("-")
    if len(parts_dash) == 3:
        if len(parts_dash[0]) == 4:
            return f"{parts_dash[2]}/{parts_dash[1]}/{parts_dash[0]}"
        return f"{parts_dash[0]}/{parts_dash[1]}/{parts_dash[2]}"
    parts_slash = raw.split("/")
    if len(parts_slash) == 3:
        if len(parts_slash[0]) == 4:
            return f"{parts_slash[2]}/{parts_slash[1]}/{parts_slash[0]}"
        return raw
    return raw
