"""
INC-09A -- reaffirms every contract fixture stays ineligible for the G5
live allowlist. This increment added two fixtures of its own
(mission_index_navigation_mock_only.json and
mission_workflow_query_mock_only.json, both MOCK_ONLY/UNCONFIRMED, added
in the dea9ffd correction for the real-Chromium proofs' navigation
contracts) alongside every fixture from INC-06/07/08. The test below does
not enumerate fixtures by name: it dynamically globs every file under
tests/fixtures/contracts/ and requires every eligibility field it finds
(top-level `eligible_for_live_allowlist`, and the same field on each entry
of a `final_endpoints` list) to be exactly False -- so a new fixture added
by any future increment is checked automatically, without needing this
test to be updated.
"""

import json
from pathlib import Path

_MISSING = object()

FIXTURES_DIR = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "contracts"


def test_all_fixture_files_declare_eligible_for_live_allowlist_false():
    checked = 0
    for path in sorted(FIXTURES_DIR.glob("*.json")):
        fixture = json.loads(path.read_text(encoding="utf-8"))
        if "eligible_for_live_allowlist" in fixture:
            assert fixture["eligible_for_live_allowlist"] is False, path.name
            checked += 1
        if "final_endpoints" in fixture:
            for entry in fixture["final_endpoints"]:
                eligible = entry.get("eligible_for_live_allowlist", _MISSING)
                assert eligible is False, f"{path.name}:{entry.get('endpoint_name')}"
                checked += 1
    assert checked > 0
