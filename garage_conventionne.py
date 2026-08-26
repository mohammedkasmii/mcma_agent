"""
garage_conventionne.py — Backward-Compatibility Bridge
======================================================
Re-exports fill_garage_conventionne, GCLogger, and matchers from browser.mode_conventionne.
"""

from browser.mode_conventionne import (
    fill_garage_conventionne,
    fill_mode_conventionne,
    match_all_rubriques,
    _match_single_rubrique,
    RUBRIQUE_MATCH_ALIASES,
    GCLogger,
)

__all__ = [
    "fill_garage_conventionne",
    "fill_mode_conventionne",
    "match_all_rubriques",
    "_match_single_rubrique",
    "RUBRIQUE_MATCH_ALIASES",
    "GCLogger",
]
