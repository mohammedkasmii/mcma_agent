"""
INC-09B amendment #2/#3 -- CalculationLedger is a pure, page-free,
Playwright-free state machine. Tested directly here, in isolation, with
NO browser/mock server and NO test-only hook anywhere on
VerifiedMissionWriter/open_verified_writer -- this is the "extract a
private pure state/evidence component and test it directly" alternative
to a production test-hook parameter (amendment #3).
"""

import pytest

from mcma.portal.writer import (
    CalculationLedger,
    FinancialSummary,
    NativeCalculationIncomplete,
    NativeCalculationMalformed,
    NativeCalculationMismatch,
    NativeCalculationStale,
    WriteAborted,
    parse_financial_summary,
)
from writer_test_support import money


def make_summary(charge_mutuelle="100.00"):
    return FinancialSummary(
        montant_charge_mutuelle=money(charge_mutuelle),
        montant_charge_societaire=money("200.00"),
        total_tva=money("50.00"),
        total_ttc=money("300.00"),
        vetuste=money("0.00"),
        franchise=money("0.00"),
        remise=money("0.00"),
        montant_arrete=money("300.00"),
        base_indemnite=money("300.00"),
    )


def test_verify_before_any_trigger_raises_write_aborted():
    ledger = CalculationLedger()
    with pytest.raises(WriteAborted):
        ledger.verify_fresh(make_summary())


def test_trigger_then_verify_with_matching_summary_succeeds():
    ledger = CalculationLedger()
    summary = make_summary()
    ledger.record_trigger(1, summary)
    assert ledger.verify_fresh(summary) is summary


def test_verify_with_disagreeing_summary_raises_mismatch():
    ledger = CalculationLedger()
    ledger.record_trigger(1, make_summary("100.00"))
    with pytest.raises(NativeCalculationMismatch):
        ledger.verify_fresh(make_summary("999.00"))


def test_mutation_after_trigger_invalidates_and_verify_raises_stale():
    ledger = CalculationLedger()
    summary = make_summary()
    ledger.record_trigger(1, summary)
    ledger.record_mutation()
    with pytest.raises(NativeCalculationStale):
        ledger.verify_fresh(summary)


def test_mutation_after_trigger_makes_even_a_matching_summary_stale():
    """The row_generation staleness check is about the MUTATION having
    happened, not about whether the summary's values happen to still
    match -- a coincidentally-identical summary after a later mutation is
    still stale, never silently accepted."""
    ledger = CalculationLedger()
    summary = make_summary()
    ledger.record_trigger(1, summary)
    ledger.record_mutation()
    with pytest.raises(NativeCalculationStale):
        ledger.verify_fresh(summary)


def test_record_trigger_rejects_non_advancing_calculation_version():
    ledger = CalculationLedger()
    ledger.record_trigger(5, make_summary())
    with pytest.raises(NativeCalculationStale):
        ledger.record_trigger(5, make_summary())
    with pytest.raises(NativeCalculationStale):
        ledger.record_trigger(3, make_summary())


def test_record_trigger_accepts_strictly_increasing_calculation_version():
    ledger = CalculationLedger()
    ledger.record_trigger(1, make_summary())
    ledger.record_trigger(2, make_summary("150.00"))  # no raise
    assert ledger.verify_fresh(make_summary("150.00")) is not None


def test_row_generation_increments_only_on_mutation():
    ledger = CalculationLedger()
    assert ledger.row_generation == 0
    ledger.record_mutation()
    assert ledger.row_generation == 1
    ledger.record_mutation()
    assert ledger.row_generation == 2


# --------------------------------------------------------------------- #
# parse_financial_summary -- missing vs malformed are distinct
# --------------------------------------------------------------------- #

_VALID_RAW = {
    "montant_charge_mutuelle": "100.00",
    "montant_charge_societaire": "200.00",
    "total_tva": "50.00",
    "total_ttc": "300.00",
    "vetuste": "0.00",
    "franchise": "0.00",
    "remise": "0.00",
    "montant_arrete": "300.00",
    "base_indemnite": "300.00",
}


def test_parse_financial_summary_accepts_complete_valid_payload():
    summary = parse_financial_summary(dict(_VALID_RAW))
    assert summary.montant_charge_mutuelle == money("100.00")


def test_parse_financial_summary_missing_field_raises_incomplete():
    raw = dict(_VALID_RAW)
    del raw["base_indemnite"]
    with pytest.raises(NativeCalculationIncomplete):
        parse_financial_summary(raw)


def test_parse_financial_summary_malformed_field_raises_malformed():
    raw = dict(_VALID_RAW)
    raw["total_ttc"] = "not-a-number"
    with pytest.raises(NativeCalculationMalformed):
        parse_financial_summary(raw)


def test_parse_financial_summary_non_dict_raises_malformed():
    with pytest.raises(NativeCalculationMalformed):
        parse_financial_summary("not-a-dict")
