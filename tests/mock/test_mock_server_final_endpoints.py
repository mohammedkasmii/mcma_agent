"""
INC-06 — final/dossier-level endpoints must be meaningful sentinels: present
(so INC-07 interception tests can prove they were never reached), always a
deliberate failure, never finalizing, hit-counted; the phantom `createDevisDet`
stays absent.
"""

import json

from conftest import FINAL_ENDPOINT_ROUTES, FIXTURES_DIR, state


def test_every_final_endpoint_is_a_registered_sentinel(client):
    for name, route in FINAL_ENDPOINT_ROUTES.items():
        resp = client.post(route, data={"probe": "1"})
        assert resp.status_code == 200, f"{name} not registered"
        body = resp.json()
        assert body["state"] == "error"
        assert body["reason"] == "FINAL_ACTION_PERMANENTLY_PROHIBITED"

    hits = state(client)["observability"]["final_endpoint_hits"]
    for name in FINAL_ENDPOINT_ROUTES:
        assert hits[name] == 1


def test_create_devis_det_phantom_is_absent(client):
    routes = {r.path for r in client.app.router.routes}
    assert not any("createDevisDet" in path for path in routes)


def test_final_endpoints_never_mutate_dossier_finalized_state(client):
    for route in FINAL_ENDPOINT_ROUTES.values():
        client.post(route, data={"probe": "1"})
    st = state(client)
    assert st["last_saved_mission"] is None
    assert st["validated_devis_payload"] is None


def test_final_endpoints_fixture_marks_all_permanently_prohibited_and_phantom_absent():
    fixture = json.loads((FIXTURES_DIR / "final_endpoints.json").read_text(encoding="utf-8"))
    assert set(fixture["phantom_endpoints_intentionally_absent"]) == {"createDevisDet"}
    for entry in fixture["final_endpoints"]:
        assert entry["classification"] == "PERMANENTLY_PROHIBITED"
        assert entry["eligible_for_live_allowlist"] is False
    assert set(FINAL_ENDPOINT_ROUTES) == {e["endpoint_name"] for e in fixture["final_endpoints"]}
