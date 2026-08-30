"""
INC-09B amendment #2 -- the PEC native-calculation MOCK_ONLY verification
adapter's response shape: `expected`/`apply_to_dom`/`calculation_version`,
ADDED alongside the original (INC-06) `summary`/`stale` shape (kept
byte-for-byte for tests/mock/test_mock_server_pec_workflow.py and
test_mock_server_readiness_simulation.py, which this file does not touch).
"""

_BASE_PAYLOAD = {
    "total_ttc": "1000.00",
    "total_tva": "166.67",
    "franchise": "50.00",
    "vetuste": "10.00",
    "remise": "0.00",
    "part_resp": "100",
}

_ALL_NINE_FIELDS = (
    "montant_charge_mutuelle",
    "montant_charge_societaire",
    "total_tva",
    "total_ttc",
    "vetuste",
    "franchise",
    "remise",
    "montant_arrete",
    "base_indemnite",
)


def _calc(client, simulate):
    return client.post(
        "/_mock/pec/native_calculation", json={**_BASE_PAYLOAD, "simulate": simulate}
    ).json()


def test_success_returns_all_nine_expected_fields_and_matching_apply_to_dom(client):
    body = _calc(client, "success")
    assert body["state"] == "success"
    assert isinstance(body["calculation_version"], int) and body["calculation_version"] >= 1
    for field in _ALL_NINE_FIELDS:
        assert field in body["expected"]
        assert field in body["apply_to_dom"]
    assert body["expected"] == body["apply_to_dom"]


def test_success_uses_exact_decimal_arithmetic_not_float():
    from mock_server import _compute_pec_financial_summary

    result = _compute_pec_financial_summary(
        {"total_ttc": "10.00", "franchise": "1.00", "vetuste": "0.00", "remise": "0.00", "part_resp": "33.33"}
    )
    # 1.00 * 33.33 / 100 = 0.3333 -> HALF_UP to 2dp = 0.33
    assert result["montant_charge_societaire"] == "0.33"


def test_mismatch_makes_expected_and_apply_to_dom_disagree(client):
    body = _calc(client, "mismatch")
    assert body["state"] == "success"
    assert body["expected"] != body["apply_to_dom"]
    assert body["expected"]["montant_charge_mutuelle"] != body["apply_to_dom"]["montant_charge_mutuelle"]
    # every OTHER field is unchanged -- only the one deliberate disagreement
    for field in _ALL_NINE_FIELDS:
        if field != "montant_charge_mutuelle":
            assert body["expected"][field] == body["apply_to_dom"][field]


def test_malformed_expected_has_an_unparseable_field(client):
    body = _calc(client, "malformed")
    assert body["state"] == "success"
    assert body["expected"]["total_ttc"] == "not-a-number"


def test_incomplete_expected_is_missing_a_required_field(client):
    body = _calc(client, "incomplete")
    assert body["state"] == "success"
    assert "base_indemnite" not in body["expected"]


def test_stale_does_not_advance_calculation_version(client):
    first = _calc(client, "success")
    stale = _calc(client, "stale")
    assert stale["calculation_version"] <= first["calculation_version"]


def test_failed_and_missing_are_distinct_error_reasons(client):
    failed = _calc(client, "failed")
    missing = _calc(client, "missing")
    assert failed["state"] == "error" and failed["reason"] == "NATIVE_CALCULATION_FAILED"
    assert missing["state"] == "error" and missing["reason"] == "MISSING_CALCULATION_RESULT"


def test_successive_success_calls_strictly_advance_calculation_version(client):
    first = _calc(client, "success")
    second = _calc(client, "success")
    assert second["calculation_version"] > first["calculation_version"]


def test_direct_charge_field_write_is_rejected_before_any_response_shape_is_built(client):
    body = client.post(
        "/_mock/pec/native_calculation",
        json={**_BASE_PAYLOAD, "simulate": "success", "DevisMontantChargeMutuelle": "999.99"},
    ).json()
    assert body["state"] == "error"
    assert body["reason"] == "DIRECT_CHARGE_FIELD_WRITE_REJECTED"
    assert "calculation_version" not in body
