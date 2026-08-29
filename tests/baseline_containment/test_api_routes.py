"""
INC-00 §6.4 — both fill-dossier API routes must be absent and non-executable.
"""

FILL_PATHS = ("/api/v1/fill-dossier", "/api/v1/fill-dossier-from-wexia")


def test_fill_dossier_routes_absent():
    from main import app

    registered = {getattr(r, "path", None) for r in app.routes}
    for path in FILL_PATHS:
        assert path not in registered, f"forbidden write route still registered: {path}"


def test_fill_dossier_posts_are_non_success():
    from fastapi.testclient import TestClient
    from main import app

    client = TestClient(app)
    for path in FILL_PATHS:
        resp = client.post(path, json={})
        # StaticFiles is mounted at "/", so 404 or 405 are both valid refusals.
        assert resp.status_code in (404, 405), (
            f"POST {path} returned {resp.status_code}; the old handler may still execute"
        )
