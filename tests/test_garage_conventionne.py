"""
tests/test_garage_conventionne.py — Unit Tests for Garage Conventionné Module
=============================================================================
Tests the deterministic matching engine, all-or-nothing guarantees,
alias resolution, and logger utilities of garage_conventionne.py.
"""

import os
import pytest
from browser.mode_conventionne import (
    GCLogger,
    match_all_rubriques,
    _match_single_rubrique,
    RUBRIQUE_MATCH_ALIASES,
)
from mapper import RUBRIQUE_CATALOG


@pytest.fixture
def mock_logger():
    return GCLogger(log_dir="temp/test_logs")


def test_gc_matching_exact_lib_rubrique(mock_logger):
    """Test matching when Table 2 row has exact LibRubrique text."""
    rubriques = [
        {"IdRubrique": "3", "LibRubrique": "TOTAL PIECES OCCASIONS / RECUPERABLES", "MontantHT": "4750.00"},
        {"IdRubrique": "7", "LibRubrique": "MAIN D'OEUVRE CARROSSERIE", "MontantHT": "1820.00"},
        {"IdRubrique": "12", "LibRubrique": "MAIN D'OEUVRE PEINTURE", "MontantHT": "1680.00"},
        {"IdRubrique": "16", "LibRubrique": "PEINTURES ET INGREDIENTS", "MontantHT": "1083.33"},
    ]

    table_rows = [
        {"index": 0, "rubrique_label": "TOTAL PIECES OCCASIONS / RECUPERABLES"},
        {"index": 1, "rubrique_label": "MAIN D'OEUVRE CARROSSERIE"},
        {"index": 2, "rubrique_label": "MAIN D'OEUVRE PEINTURE"},
        {"index": 3, "rubrique_label": "PEINTURES ET INGREDIENTS"},
    ]

    matches = match_all_rubriques(rubriques, table_rows, mock_logger)
    assert len(matches) == 4
    assert matches[0]["target_label"] == "TOTAL PIECES OCCASIONS / RECUPERABLES"
    assert matches[1]["target_label"] == "MAIN D'OEUVRE CARROSSERIE"
    assert matches[2]["target_label"] == "MAIN D'OEUVRE PEINTURE"
    assert matches[3]["target_label"] == "PEINTURES ET INGREDIENTS"


def test_gc_matching_with_aliases_and_accents(mock_logger):
    """Test matching with variations in accents, punctuation, and aliases."""
    rubriques = [
        {"IdRubrique": "3", "LibRubrique": "FOURNITURES CARROSSERIE (RECUPERABLES)", "MontantHT": "5000.00"},
        {"IdRubrique": "7", "LibRubrique": "MAIN D'OEUVRE CARROSSERIE", "MontantHT": "2000.00"},
    ]

    table_rows = [
        {"index": 0, "rubrique_label": "PIECES OCCASIONS / RECUPERABLES"},
        {"index": 1, "rubrique_label": "MO CARROSSERIE"},
    ]

    matches = match_all_rubriques(rubriques, table_rows, mock_logger)
    assert len(matches) == 2
    assert matches[0]["rubrique"]["IdRubrique"] == "3"
    assert matches[1]["rubrique"]["IdRubrique"] == "7"


def test_gc_all_or_nothing_fails_closed(mock_logger):
    """
    Test strict all-or-nothing guarantee:
    If 3 rubriques are expected but only 2 exist in Table 2,
    match_all_rubriques MUST return [] to prevent partial writes.
    """
    rubriques = [
        {"IdRubrique": "1", "LibRubrique": "FOURNITURES CARROSSERIE (ORIGINES)", "MontantHT": "3000.00"},
        {"IdRubrique": "7", "LibRubrique": "MAIN D'OEUVRE CARROSSERIE", "MontantHT": "1500.00"},
        {"IdRubrique": "25", "LibRubrique": "COLLE", "MontantHT": "400.00"},  # Missing from table
    ]

    table_rows = [
        {"index": 0, "rubrique_label": "FOURNITURES CARROSSERIE (ORIGINES)"},
        {"index": 1, "rubrique_label": "MAIN D'OEUVRE CARROSSERIE"},
    ]

    matches = match_all_rubriques(rubriques, table_rows, mock_logger)
    # MUST return empty list
    assert matches == []


def test_gc_unique_row_assignment(mock_logger):
    """Test that two rubriques cannot claim the same Table 2 row."""
    rubriques = [
        {"IdRubrique": "1", "LibRubrique": "FOURNITURES CARROSSERIE (ORIGINES)", "MontantHT": "1000.00"},
        {"IdRubrique": "2", "LibRubrique": "FOURNITURES CARROSSERIE (ADAPTABLES)", "MontantHT": "1000.00"},
    ]

    # Only 1 row in the table
    table_rows = [
        {"index": 0, "rubrique_label": "FOURNITURES CARROSSERIE (ORIGINES)"},
    ]

    matches = match_all_rubriques(rubriques, table_rows, mock_logger)
    assert matches == []  # Cannot match all 2


def test_gc_logger_creates_file_and_summarizes(tmp_path):
    """Test that GCLogger creates valid JSON logs with correct counters."""
    log_dir = str(tmp_path / "logs")
    logger = GCLogger(log_dir=log_dir)

    logger.log("STEP_1", "OK", "Step 1 passed")
    logger.log("STEP_2", "WARN", "Step 2 had warning")
    logger.log("STEP_3", "ERROR", "Step 3 failed")

    summary = logger.summary()
    assert summary["ok"] == 1
    assert summary["warnings"] == 1
    assert summary["errors"] == 1
    assert summary["total_steps"] == 3
    assert os.path.exists(summary["log_file"])
