"""
INC-06 — extended mock server surface (docs/implementation/increments/20-portal-safety.md).
"""

import ast
from pathlib import Path

MOCK_SERVER_PATH = Path(__file__).resolve().parents[2] / "mock_server.py"


def test_mock_server_serves_notification_datatable(client):
    resp = client.post(
        "/SinAuto_MCMA/expertise/notification/getAlerte/CodeAlerte/RELANCES",
        data={"length": "-1", "iDisplayLength": "-1"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "data" in body and isinstance(body["data"], list)
    assert "iTotalRecords" in body and "iTotalDisplayRecords" in body


def test_mock_server_row_endpoints_exist(client):
    routes = {r.path for r in client.app.router.routes}
    assert "/SinAuto_MCMA/expertise/gestionExpert/createRapportDefDet" in routes
    assert "/SinAuto_MCMA/expertise/gestionexpert/updateDevisDet" in routes


def test_mock_server_binds_loopback_only():
    tree = ast.parse(MOCK_SERVER_PATH.read_text(encoding="utf-8"))
    found_loopback = False
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "run"
        ):
            for kw in node.keywords:
                if kw.arg == "host":
                    assert isinstance(kw.value, ast.Constant) and kw.value.value == "127.0.0.1"
                    found_loopback = True
    assert found_loopback, "uvicorn.run(..., host=...) not found"
    source = MOCK_SERVER_PATH.read_text(encoding="utf-8")
    assert "0.0.0.0" not in source


def test_final_endpoint_hit_count_starts_at_zero(client):
    from mock_test_support import state, FINAL_ENDPOINT_ROUTES

    hits = state(client)["observability"]["final_endpoint_hits"]
    for name in FINAL_ENDPOINT_ROUTES:
        assert hits[name] == 0
