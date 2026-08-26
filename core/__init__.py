"""
core package — Central configuration, constants, math utilities, and logging.
"""

from core.config import TEST_MODE, BASE_URL, DASHBOARD_URL, AUTH_STATE_FILE
from core.constants import (
    RUBRIQUE_CATALOG,
    RUBRIQUE_MATCH_ALIASES,
    PART_ORIGIN_ORIGINAL,
    PART_ORIGIN_ADAPTABLE,
    PART_ORIGIN_RECOVERED,
    SYSTEM_RUBRIQUE_MATRIX,
    DEFAULT_TVA_RATE,
    CENT,
)
from core.utils import (
    to_decimal,
    quantize_money,
    format_money,
    normalize_text,
    normalize_registration,
    extract_search_matricule,
    format_date_dd_mm_yyyy,
)
from core.logger import StructuredLogger, capture_screenshot
