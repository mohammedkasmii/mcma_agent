"""Wexia uses total_cost two different ways, and both are real.

In most payloads total_cost is HT and final_cost is HT + tax. In others
total_cost EQUALS final_cost -- it is TTC. Treating it as HT everywhere
rejects internally coherent dossiers; ignoring it when it disagrees would
throw away the only cross-check on the total.

The shape is therefore decided by arithmetic. Nothing about the dossier's
identity -- document_type, scenario_type, status, filename, version --
may select it, and these tests pin that both directions fail closed when
the numbers do not add up.

No real dossier content appears here. The figures are the minimal
arithmetic from the relationship analysis.
"""

from decimal import Decimal

import pytest

from mcma.mapping.wexia import WexiaChiffrage
from mcma.planning.plan import PlanBuildError, _validate_chiffrage_totals

HT = Decimal("100")


def _chiffrage(**kwargs):
    return WexiaChiffrage(**kwargs)


def _validate(ht=HT, **kwargs):
    _validate_chiffrage_totals(_chiffrage(**kwargs), ht)


# --------------------------------------------------------------------- #
# The two proven shapes
# --------------------------------------------------------------------- #


def test_shape_a_total_cost_is_ht():
    """line HT 100 / parts 80 + labour 20 / tax 20 / total_cost 100 /
    final_cost 120."""
    _validate(
        total_parts_cost="80", total_labor_cost="20",
        tax_amount="20", total_cost="100", final_cost="120",
    )


def test_shape_b_total_cost_is_ttc():
    """Same dossier arithmetic, but total_cost carries TTC. Internally
    coherent, and previously rejected."""
    _validate(
        total_parts_cost="80", total_labor_cost="20",
        tax_amount="20", total_cost="120", final_cost="120",
    )


def test_the_shape_is_decided_by_arithmetic_alone():
    """The same numbers must validate regardless of what the payload says
    it is -- a devis, a facture, approved, submitted, repair or
    replacement."""
    for scenario, status in (
        ("repair", "approved"), ("replacement", "submitted"),
        ("quote", "draft"), (None, None),
    ):
        _validate(
            scenario_type=scenario, status=status,
            total_parts_cost="80", total_labor_cost="20",
            tax_amount="20", total_cost="120", final_cost="120",
        )


# --------------------------------------------------------------------- #
# HT is validated against the detailed breakdown
# --------------------------------------------------------------------- #


def test_an_aggregate_that_does_not_match_the_lines_fails_closed():
    with pytest.raises(PlanBuildError, match="total_parts_cost \\+ total_labor_cost"):
        _validate(
            total_parts_cost="80", total_labor_cost="19",
            tax_amount="20", total_cost="100", final_cost="120",
        )


def test_only_one_half_of_the_breakdown_fails_closed():
    """Absence is not zero. Treating the missing side as zero would
    validate the mapped HT against a number that is not the HT."""
    with pytest.raises(PlanBuildError, match="only one of"):
        _validate(total_parts_cost="80", tax_amount="20", total_cost="100", final_cost="120")
    with pytest.raises(PlanBuildError, match="only one of"):
        _validate(total_labor_cost="20", tax_amount="20", total_cost="100", final_cost="120")


def test_an_explicit_zero_component_is_honoured():
    """A dossier with no labour at all is different from one that omits
    the field."""
    _validate(
        ht=Decimal("80"),
        total_parts_cost="80", total_labor_cost="0",
        tax_amount="16", total_cost="80", final_cost="96",
    )


def test_the_legacy_shape_without_a_breakdown_still_works():
    """Fixtures that predate these fields carry total_cost as HT, and must
    keep validating under exactly that rule."""
    _validate(tax_amount="20", total_cost="100")
    with pytest.raises(PlanBuildError):
        _validate(tax_amount="20", total_cost="101")


# --------------------------------------------------------------------- #
# TTC must be proven, never assumed
# --------------------------------------------------------------------- #


def test_a_final_cost_that_is_not_ht_plus_tax_fails_closed():
    with pytest.raises(PlanBuildError, match="differs from final_cost"):
        _validate(
            total_parts_cost="80", total_labor_cost="20",
            tax_amount="20", total_cost="100", final_cost="119",
        )


def test_total_cost_matching_neither_role_fails_closed():
    with pytest.raises(PlanBuildError, match="matches neither HT"):
        _validate(
            total_parts_cost="80", total_labor_cost="20",
            tax_amount="20", total_cost="110", final_cost="120",
        )


def test_shape_b_is_never_inferred_without_final_cost():
    """A total_cost that merely differs from HT proves nothing. Without
    final_cost there is no evidence of what TTC would be, so accepting it
    would be a guess."""
    with pytest.raises(PlanBuildError, match="matches neither HT"):
        _validate(
            total_parts_cost="80", total_labor_cost="20",
            tax_amount="20", total_cost="120",
        )


def test_a_missing_total_cost_or_tax_still_fails_closed_earlier():
    """The existing absent-is-not-zero guard runs before this validation
    and is unchanged."""
    with pytest.raises(PlanBuildError, match="absent is not zero"):
        _build(_dossier(total_parts_cost="80", total_labor_cost="20", final_cost="120"))


# --------------------------------------------------------------------- #
# Rounding
# --------------------------------------------------------------------- #


def test_a_one_centime_difference_is_tolerated_and_two_is_not():
    _validate(
        total_parts_cost="79.99", total_labor_cost="20",
        tax_amount="20", total_cost="100", final_cost="120",
    )
    with pytest.raises(PlanBuildError):
        _validate(
            total_parts_cost="79.98", total_labor_cost="20",
            tax_amount="20", total_cost="100", final_cost="120",
        )


# --------------------------------------------------------------------- #
# End to end through the real planner
# --------------------------------------------------------------------- #


def _dossier(**chiffrage_fields):
    """Minimal payload whose lines map deterministically: one original
    part and one declared labour line."""
    return {
        "vehicule": {"license_plate": "77001-C-3"},
        "dossier": {
            "id_sinistre": "699001",
            "mission_type": "normal",
            "incident_description": "MODE NORMAL",
            "is_reform": False,
        },
        "chiffrages": [
            dict(
                status="approved",
                scenario_type="repair",
                lignes_pieces=[
                    {"item_type": "part", "item_name": "AILE AVANT",
                     "part_type": "original", "is_original": True, "subtotal": "80"},
                    {"item_type": "labor", "item_name": "carrosserie", "subtotal": "20"},
                ],
                **chiffrage_fields,
            )
        ],
    }


def _build(payload):
    from mcma.mapping.wexia import parse_wexia
    from mcma.planning.plan import detect_workflow
    from mcma.planning.registry import default_registry, workflow_name_for

    parsed = parse_wexia(payload)
    return default_registry().get(workflow_name_for(detect_workflow(parsed)))(parsed)


def test_a_shape_b_dossier_produces_a_writeable_plan():
    """The end the whole change exists for: an internally coherent
    dossier whose total_cost is TTC now plans instead of failing."""
    plan = _build(_dossier(
        total_parts_cost="80", total_labor_cost="20",
        tax_amount="20", total_cost="120", final_cost="120",
    ))
    assert list(plan.needs_review) == []
    assert len(plan.steps) == 2
    assert sum(step.ht.amount for step in plan.steps) == Decimal("100")


def test_a_shape_a_dossier_still_produces_a_writeable_plan():
    plan = _build(_dossier(
        total_parts_cost="80", total_labor_cost="20",
        tax_amount="20", total_cost="100", final_cost="120",
    ))
    assert list(plan.needs_review) == []
    assert len(plan.steps) == 2


def test_an_incoherent_dossier_still_fails_closed_end_to_end():
    with pytest.raises(PlanBuildError):
        _build(_dossier(
            total_parts_cost="80", total_labor_cost="20",
            tax_amount="20", total_cost="110", final_cost="120",
        ))


def test_the_tva_allocation_is_unchanged():
    """C.2.2 showed the allocator was never the problem -- the failures
    came from unmapped rows. It must stay exactly as it was."""
    plan = _build(_dossier(
        total_parts_cost="80", total_labor_cost="20",
        tax_amount="20", total_cost="120", final_cost="120",
    ))
    assert sum(step.tva.amount for step in plan.steps) == Decimal("20")


def test_chiffrage_selection_is_untouched():
    """Two active approved candidates must still fail closed. Preferring
    repair, devis, the newest or the highest version is a business
    decision, not an arithmetic one."""
    from mcma.planning.plan import _select_chiffrage

    payload = _dossier(
        total_parts_cost="80", total_labor_cost="20",
        tax_amount="20", total_cost="120", final_cost="120",
    )
    second = dict(payload["chiffrages"][0])
    second["scenario_type"] = "replacement"
    payload["chiffrages"].append(second)

    from mcma.mapping.wexia import parse_wexia

    with pytest.raises(PlanBuildError, match="multiple distinct approved chiffrages"):
        _select_chiffrage(parse_wexia(payload).chiffrages)
