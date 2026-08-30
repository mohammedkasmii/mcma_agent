"""
INC-06 — calculation + exact summary verification must be required before a
simulated workflow can be considered ready; stale/missing/failed/mismatched
results are never ready. The readiness check itself is test-only logic (no
INC-06 production readiness/executor code exists yet — that is INC-12).
"""

import pytest


def _is_ready(calc_response: dict, readback_response: dict) -> bool:
    if calc_response.get("state") != "success":
        return False
    computed = calc_response.get("summary")
    if computed is None:
        return False
    stored = readback_response.get("summary")
    if stored is None:
        return False
    if stored.get("stale"):
        return False
    return stored == computed


@pytest.mark.parametrize("route_prefix", ["normal", "pec"])
def test_success_reaches_ready(client, route_prefix):
    base = {"total_ttc": "1000.00", "franchise": "0", "vetuste": "0", "remise": "0", "part_resp": "100"}
    calc = client.post(f"/_mock/{route_prefix}/native_calculation", json={**base, "simulate": "success"}).json()
    readback = client.get(f"/_mock/{route_prefix}/financial_summary").json()
    assert _is_ready(calc, readback) is True


@pytest.mark.parametrize("route_prefix", ["normal", "pec"])
@pytest.mark.parametrize("simulate", ["stale", "missing", "failed", "mismatch"])
def test_stale_missing_failed_mismatch_never_ready(client, route_prefix, simulate):
    base = {"total_ttc": "1000.00", "franchise": "0", "vetuste": "0", "remise": "0", "part_resp": "100"}
    calc = client.post(
        f"/_mock/{route_prefix}/native_calculation", json={**base, "simulate": simulate}
    ).json()
    readback = client.get(f"/_mock/{route_prefix}/financial_summary").json()
    assert _is_ready(calc, readback) is False
