"""
INC-02 — golden characterization of the CURRENT baseline WexiaToDossierMapper.

These goldens pin observed behavior so later refactors are provably
behavior-preserving. The defect golden DELIBERATELY captures known-defective
behavior (see test docstrings); INC-04/05 intentionally supersede those rules
in the new `mcma.domain` / `mcma.planning` packages (with a documented diff in
tests/domain/test_supersedes_defect_goldens.py). The baseline mapper itself is
NOT fixed here.
"""

import json
from pathlib import Path

from mapper import WexiaToDossierMapper

HERE = Path(__file__).resolve().parent
FIXTURES = HERE.parent / "fixtures" / "characterization"
GOLDENS = HERE / "goldens"


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _map(fixture_name):
    fixture = _load(FIXTURES / fixture_name)
    fixture.pop("_comment", None)
    return WexiaToDossierMapper().map(fixture)


def test_mapper_golden_normal_synthetic():
    """Clean-path golden: approved chiffrage, three-origin parts, labour line,
    exact Decimal totals with last-group TVA remainder allocation."""
    golden = _load(GOLDENS / "mapper_normal_synthetic.golden.json")
    assert _map("wexia_normal_synthetic.json") == golden


def test_mapper_golden_known_defects():
    """DEFECT GOLDEN — captures current DEFECTIVE behavior on purpose:
      - F13: a glass line (PARE-BRISE) folds into rubrique 1, never 19-24;
      - F15: labour 'module electronique' hits the unrestricted 'mo' substring
        and lands in rubrique 7 (carrosserie), not electrique;
      - F33: 'radiateur eau' is keyword-inferred into mecanique rubrique 4;
      - F14: out-of-catalogue mcma_rubric_id '99' is silently ignored and the
        line is re-inferred (rubrique 2) instead of failing closed;
      - F11-adjacent: insured_type location_voiture only warns/needs_review,
        while the payload is still produced.
    INC-04/05 intentionally supersede every one of these in mcma.* (fail-closed
    or corrected mapping); this golden continues to document the BASELINE."""
    golden = _load(GOLDENS / "mapper_defects_synthetic.golden.json")
    result = _map("wexia_defects_synthetic.json")
    assert result == golden

    # Explicit pins so the defect capture is self-describing:
    rub_ids = [r["IdRubrique"] for r in result["rubriques"]]
    assert rub_ids == ["1", "7", "4", "2"], "defect capture drifted"
    assert result["mapping_status"] == "needs_review"


def test_mapper_golden_se00009_style_fallback():
    """The se00009-style fallback shape used by the existing suite maps with
    status needs_review (un-inferable recoverable TVA) — pinned via the same
    defect fixture's checkbox/warning behavior."""
    result = _map("wexia_defects_synthetic.json")
    assert any("insured_type=location_voiture" in w for w in result["warnings"])
    assert "TvaRecupI" not in result["checkboxes"]


def test_mapper_golden_negative_tva_defect():
    """DEFECT GOLDEN (F17) — captures current DEFECTIVE behavior on purpose:
    the baseline's last-group TVA remainder is unguarded and goes NEGATIVE
    (Taxe -15.00) while every total check still passes. INC-04 intentionally
    supersedes this: the new domain fails closed with
    NeedsReview(INVALID_TAX_ALLOCATION) (see
    tests/domain/test_supersedes_defect_goldens.py)."""
    golden = _load(GOLDENS / "mapper_negative_tva_synthetic.golden.json")
    result = _map("wexia_negative_tva_synthetic.json")
    assert result == golden
    taxes = [r["Taxe"] for r in result["rubriques"]]
    assert taxes == ["20.00", "-15.00"], "F17 defect capture drifted"
