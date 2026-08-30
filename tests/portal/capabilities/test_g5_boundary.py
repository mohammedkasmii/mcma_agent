"""
INC-08 -- all contract records remain test-only and ineligible for the G5
live allowlist. Reaffirmed under this increment's own test surface too.
"""

import json

from capabilities_test_support import FIXTURES_DIR

_MISSING = object()


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
