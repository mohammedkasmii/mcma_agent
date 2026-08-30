"""
INC-07 amendment #6 -- the G5 boundary, reaffirmed from portal's own test
surface. No INC-06 evidence fixture can be converted into an approved live
contract. Missing fields must FAIL the check, never be treated as False.
"""

import json

from portal_test_support import FIXTURES_DIR

_MISSING = object()

ROW_AND_CALC_FIXTURES = (
    "normal_add_row.json",
    "pec_edit_row.json",
    "pec_native_recalc.json",
    "normal_native_recalc_mock_only.json",
)


def test_row_and_calc_fixtures_require_explicit_unconfirmed_and_ineligible():
    for name in ROW_AND_CALC_FIXTURES:
        fixture = json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))
        eligible = fixture.get("eligible_for_live_allowlist", _MISSING)
        status = fixture.get("g5_live_contract_status", _MISSING)
        assert eligible is False, f"{name}: eligible_for_live_allowlist missing or not False"
        assert status == "UNCONFIRMED", f"{name}: g5_live_contract_status missing or not UNCONFIRMED"


def test_all_fixture_files_declare_eligible_for_live_allowlist_false():
    for path in sorted(FIXTURES_DIR.glob("*.json")):
        fixture = json.loads(path.read_text(encoding="utf-8"))
        if "eligible_for_live_allowlist" in fixture:
            assert fixture["eligible_for_live_allowlist"] is False, path.name
        if "final_endpoints" in fixture:
            for entry in fixture["final_endpoints"]:
                eligible = entry.get("eligible_for_live_allowlist", _MISSING)
                assert eligible is False, f"{path.name}:{entry.get('endpoint_name')}"


def test_no_fixture_declares_a_live_selector_or_endpoint():
    fixture = json.loads((FIXTURES_DIR / "normal_native_recalc_mock_only.json").read_text(encoding="utf-8"))
    assert fixture["live_selector"] is None
    assert fixture["live_endpoint"] is None
    assert fixture["mock_only"] is True
