"""INC-04 — documented intentional diff versus the INC-02 defect goldens.

The INC-02 goldens (tests/characterization/goldens/mapper_defects_synthetic
.golden.json) capture the BASELINE mapper's known-defective behavior. The
baseline mapper is untouched (until INC-22); this test records how the NEW
mcma.domain rules intentionally supersede each captured defect:

  golden line                      baseline    new domain (this test)
  PARE-BRISE part                  rubrique 1  fail closed / 19-24 (F13)
  'module electronique' labour     rubrique 7  NeedsReview UNKNOWN_LABOUR (F15)
  'radiateur eau' part (origine)   rubrique 4  rubrique 1 (origin-only, F33)
  mcma_rubric_id '99'              re-inferred NeedsReview UNKNOWN_RUBRIC_ID (F14)
"""

import json
from pathlib import Path

from mcma.domain.results import Mapped, NeedsReview, ReasonCode
from mcma.domain.rubriques import (
    classify_glass_line,
    classify_labour_line,
    classify_ordinary_part,
    resolve_explicit_rubrique,
)
from mcma.domain.values import RubriqueId

GOLDEN = (
    Path(__file__).resolve().parents[1]
    / "characterization"
    / "goldens"
    / "mapper_defects_synthetic.golden.json"
)


def test_domain_supersedes_defect_goldens():
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    baseline_ids = [r["IdRubrique"] for r in golden["rubriques"]]
    assert baseline_ids == ["1", "7", "4", "2"], "INC-02 defect golden changed unexpectedly"

    # F13: glass no longer folds into rubrique 1 — without an operation it
    # fails closed; with one it maps into 19-24.
    assert isinstance(classify_glass_line("PARE-BRISE", None), NeedsReview)
    assert classify_glass_line("PARE-BRISE", "remplacement") == Mapped(RubriqueId("22"))

    # F15: 'module electronique' never classifies as labour via 'mo' substring.
    result = classify_labour_line(operation_type=None, labor_type_id=None, text="module electronique")
    assert isinstance(result, NeedsReview)
    assert result.reason is ReasonCode.UNKNOWN_LABOUR

    # F33: 'radiateur eau' with origin 'origine' is an ordinary part -> 1,
    # never keyword-inferred into mecanique 4.
    assert classify_ordinary_part(part_type="origine", is_original=None) == Mapped(
        RubriqueId("1")
    )

    # F14: out-of-catalogue id 99 fails closed instead of silent re-inference.
    result = resolve_explicit_rubrique("99")
    assert isinstance(result, NeedsReview)
    assert result.reason is ReasonCode.UNKNOWN_RUBRIC_ID


def test_domain_supersedes_negative_tva_defect_golden():
    """F17: the baseline golden (mapper_negative_tva_synthetic.golden.json)
    pins Taxe -15.00 on the last rubrique. The new domain fails closed with
    NeedsReview(INVALID_TAX_ALLOCATION) — no clamp, no redistribution."""
    from mcma.core.money import Money
    from mcma.domain.results import tva_allocation_result

    golden_path = GOLDEN.parent / "mapper_negative_tva_synthetic.golden.json"
    golden = json.loads(golden_path.read_text(encoding="utf-8"))
    assert [r["Taxe"] for r in golden["rubriques"]] == ["20.00", "-15.00"]

    result = tva_allocation_result([Money.of("100.00"), Money.of("10.00")], Money.of("5.00"))
    assert isinstance(result, NeedsReview)
    assert result.reason is ReasonCode.INVALID_TAX_ALLOCATION
