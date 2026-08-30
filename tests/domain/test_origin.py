"""INC-04 — three-origin rule (B.1): ordinary parts map ONLY by origin to
1/2/3; no keyword inference of 4-6/13-15/10-11; unknown fails closed."""

import inspect

from mcma.domain.results import Mapped, NeedsReview, ReasonCode
from mcma.domain.rubriques import classify_ordinary_part
from mcma.domain.values import RubriqueId


def test_three_origin_maps_1_2_3():
    cases = {
        "1": ("original", "origine", "oem", "neuf", "neuve", "new"),
        "2": ("adaptable", "equivalent", "aftermarket"),
        "3": ("recuperation", "recuperable", "occasion", "used"),
    }
    for rubrique, aliases in cases.items():
        for alias in aliases:
            result = classify_ordinary_part(part_type=alias, is_original=None)
            assert result == Mapped(RubriqueId(rubrique)), (alias, result)


def test_is_original_true_maps_to_1():
    assert classify_ordinary_part(part_type=None, is_original=True) == Mapped(RubriqueId("1"))


def test_no_keyword_inference_of_4_6_or_13_15():
    """Structural: the classifier takes NO description/system-hint input, so
    rubriques 4-6/10-11/13-15 cannot be produced for an ordinary part."""
    params = set(inspect.signature(classify_ordinary_part).parameters)
    assert params == {"part_type", "is_original"}, (
        "classify_ordinary_part must not accept a description/system hint"
    )
    # And behaviorally: every valid origin still lands in 1/2/3 only.
    for alias in ("original", "adaptable", "occasion"):
        result = classify_ordinary_part(part_type=alias, is_original=None)
        assert isinstance(result, Mapped)
        assert result.value.value in {"1", "2", "3"}


def test_unknown_part_origin_fails_closed():
    for bad in (None, "", "radiateur", "mystery", "originel?"):
        result = classify_ordinary_part(part_type=bad, is_original=None)
        assert isinstance(result, NeedsReview), bad
        assert result.reason is ReasonCode.UNKNOWN_PART_ORIGIN


def test_contradictory_origin_signals_fail_closed():
    """part_type says adaptable but is_original=True: contradictory → closed."""
    result = classify_ordinary_part(part_type="adaptable", is_original=True)
    assert isinstance(result, NeedsReview)
    assert result.reason is ReasonCode.UNKNOWN_PART_ORIGIN


def test_symmetric_origin_contradiction_fails_closed():
    """G1 review M2: is_original=False vs part_type 'origine' is just as
    contradictory as the mirror case."""
    result = classify_ordinary_part(part_type="origine", is_original=False)
    assert isinstance(result, NeedsReview)
    assert result.reason is ReasonCode.UNKNOWN_PART_ORIGIN
