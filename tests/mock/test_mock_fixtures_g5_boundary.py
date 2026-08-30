"""
INC-06 correction #1 — recovered evidence is not G5 approval. No fixture
produced by this increment may be eligible for the live allowlist; G5 still
requires separate agency contract capture, comparison, approval metadata,
deployed-commit binding, and safety evidence.
"""

import json

from conftest import FIXTURES_DIR

ALL_FIXTURE_FILES = sorted(FIXTURES_DIR.glob("*.json"))

ALLOWED_EVIDENCE_STATUSES = {
    "RECOVERED_BASELINE_EVIDENCE",
    "UNCONFIRMED_LIVE_CONTRACT",
    "MOCK_ONLY",
}


def _iter_eligibility_entries(fixture: dict):
    """Yield every dict in the fixture (top-level and nested lists) that
    declares eligible_for_live_allowlist, so both flat and list-shaped
    fixtures are covered uniformly."""
    if "eligible_for_live_allowlist" in fixture:
        yield fixture
    for value in fixture.values():
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict) and "eligible_for_live_allowlist" in item:
                    yield item


def test_at_least_seven_fixture_files_exist():
    assert len(ALL_FIXTURE_FILES) >= 7


def test_no_inc06_fixture_is_eligible_for_the_live_allowlist():
    checked = 0
    for path in ALL_FIXTURE_FILES:
        fixture = json.loads(path.read_text(encoding="utf-8"))
        for entry in _iter_eligibility_entries(fixture):
            assert entry["eligible_for_live_allowlist"] is False, path.name
            checked += 1
    assert checked > 0, "no fixture declared eligible_for_live_allowlist at all"


def test_row_write_fixtures_never_use_ambiguous_confirmed_classification():
    """createRapportDefDet, updateDevisDet, and DevisCalculerMontantCharge must
    never be tagged with the ambiguous 'CONFIRMED_RECOVERED_EVIDENCE' /
    'mock_only: false' pairing that would read as G5 approval."""
    for name in ("normal_add_row.json", "pec_edit_row.json", "pec_native_recalc.json"):
        fixture = json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))
        dumped = json.dumps(fixture)
        assert "CONFIRMED_RECOVERED_EVIDENCE" not in dumped, name
        assert fixture.get("mock_only") is not False, name


def test_normal_and_pec_row_fixtures_declare_g5_unconfirmed():
    for name in ("normal_add_row.json", "pec_edit_row.json", "pec_native_recalc.json"):
        fixture = json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))
        assert fixture["evidence_status"] in ALLOWED_EVIDENCE_STATUSES
        assert fixture["g5_live_contract_status"] == "UNCONFIRMED"
        assert fixture["eligible_for_live_allowlist"] is False
        assert fixture["mock_route"] is True


def test_final_endpoints_fixture_entries_declare_g5_unconfirmed():
    fixture = json.loads((FIXTURES_DIR / "final_endpoints.json").read_text(encoding="utf-8"))
    for entry in fixture["final_endpoints"]:
        assert entry["eligible_for_live_allowlist"] is False
