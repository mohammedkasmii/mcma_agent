"""INC-19 -- mcma.app.dashboard: serves the static shell + CSP header;
carries no write route of its own (every state-changing action goes
through mcma.app.api's authenticated/CSRF-protected endpoints)."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from mcma.app.dashboard import CONTENT_SECURITY_POLICY, mount_dashboard


def _app() -> TestClient:
    app = FastAPI()
    mount_dashboard(app)
    return TestClient(app)


def test_index_is_served_with_csp_header():
    client = _app()
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-security-policy"] == CONTENT_SECURITY_POLICY
    assert "text/html" in response.headers["content-type"]


def test_app_js_is_served_as_a_static_file():
    client = _app()
    response = client.get("/static/app.js")
    assert response.status_code == 200
    assert "window.mcmaDashboard" in response.text


def test_style_css_is_served():
    client = _app()
    response = client.get("/static/style.css")
    assert response.status_code == 200


def test_dashboard_module_defines_no_write_route():
    """mcma.app.dashboard mounts ONLY static assets + one GET route --
    every state-changing action is delegated to mcma.app.api, never
    defined here."""
    app = FastAPI()
    mount_dashboard(app)
    for route in app.routes:
        methods = getattr(route, "methods", None) or set()
        assert "POST" not in methods
        assert "PUT" not in methods
        assert "DELETE" not in methods


def test_no_enregistrer_valider_cloture_ged_control_in_served_assets():
    """Structural: mentioning that the EMPLOYEE must manually click
    Valider/Clôture is required instructional text (K); what must never
    exist is a CONTROL (a button/input) that performs one, or any JS
    function/selector wired to click one -- checked as an id/onclick/
    function-name pattern, not a bare substring match against prose."""
    client = _app()
    index_html = client.get("/").text
    app_js = client.get("/static/app.js").text

    forbidden_control_ids = (
        "enregistrer-btn", "valider-btn", "cloture-btn", "cloture-btn", "ged-btn",
    )
    for control_id in forbidden_control_ids:
        assert f'id="{control_id}"' not in index_html

    forbidden_js_identifiers = ("clickValider", "clickCloture", "clickEnregistrer", "clickGed", "submitToPortal")
    for identifier in forbidden_js_identifiers:
        assert identifier not in app_js
