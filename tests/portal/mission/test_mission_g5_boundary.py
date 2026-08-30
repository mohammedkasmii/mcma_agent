"""
INC-09A -- reaffirms every contract fixture stays ineligible for the G5
live allowlist. No new fixture is added by this increment (workflow
detection and identity scraping use fixed DOM selectors, not a new HTTP
route/contract), so this is a pure reaffirmation, same pattern as INC-06/
07/08.
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
