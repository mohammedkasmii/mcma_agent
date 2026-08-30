"""
INC-02 — golden characterization of the CURRENT garage-conventionne matcher
(`match_all_rubriques` / `_match_single_rubrique`), including its latent
matching defect (F16). The matcher is superseded by exact-IdRubrique row
selection at INC-09; these goldens document the baseline until then.
"""

import json
from pathlib import Path

from browser.mode_conventionne import match_all_rubriques

HERE = Path(__file__).resolve().parent
GOLDENS = HERE / "goldens"


class _Logger:
    log_path = "<in-memory>"

    def log(self, *args, **kwargs):
        pass

    def summary(self):
        return {"errors": 0, "log_file": self.log_path}


def _matches(rubriques, table_rows):
    raw = match_all_rubriques(rubriques, table_rows, _Logger())
    return [
        {
            "IdRubrique": m["rubrique"]["IdRubrique"],
            "target_label": m["target_label"],
            "target_index": m["target_index"],
            "match_method": m["match_method"],
        }
        for m in raw
    ]


def test_matcher_golden_exact_and_alias():
    """Exact normalized-label matches and known-alias matches (17 <- 'marbre')."""
    rubriques = [
        {"IdRubrique": "7", "LibRubrique": "MAIN D'OEUVRE CARROSSERIE", "MontantHT": "100.00"},
        {"IdRubrique": "17", "LibRubrique": "MARBRE", "MontantHT": "50.00"},
    ]
    table_rows = [
        {"index": 0, "rubrique_label": "MAIN D'OEUVRE CARROSSERIE"},
        {"index": 1, "rubrique_label": "PASSAGE AU MARBRE"},
    ]
    golden = json.loads((GOLDENS / "matcher_exact_alias.golden.json").read_text(encoding="utf-8"))
    assert _matches(rubriques, table_rows) == golden


def test_matcher_golden_substring_wrong_row_defect():
    """DEFECT GOLDEN (F16) — captures current DEFECTIVE behavior on purpose:
    rubrique 25 (COLLE) matched against a lone 'KIT COLLE VITRE' row succeeds
    via bidirectional substring matching, assigning the WRONG row. INC-09
    supersedes this with exact-IdRubrique selection that fails closed."""
    rubriques = [{"IdRubrique": "25", "LibRubrique": "COLLE", "MontantHT": "10.00"}]
    table_rows = [{"index": 0, "rubrique_label": "KIT COLLE VITRE"}]
    golden = json.loads(
        (GOLDENS / "matcher_substring_defect.golden.json").read_text(encoding="utf-8")
    )
    result = _matches(rubriques, table_rows)
    assert result == golden
    assert result[0]["target_label"] == "KIT COLLE VITRE", "defect capture drifted"


def test_matcher_all_or_nothing_abort_characterized():
    """One unmatched rubrique aborts the whole match with an empty result."""
    rubriques = [
        {"IdRubrique": "7", "LibRubrique": "MAIN D'OEUVRE CARROSSERIE", "MontantHT": "100.00"},
        {"IdRubrique": "12", "LibRubrique": "MAIN D'OEUVRE PEINTURE", "MontantHT": "80.00"},
    ]
    table_rows = [{"index": 0, "rubrique_label": "MAIN D'OEUVRE CARROSSERIE"}]
    assert _matches(rubriques, table_rows) == []
