"""
Production serving of Frontend V2: the built SPA is reachable at every
declared route, the API keeps winning, and an unknown backend path is still
a backend 404 rather than an HTML 200.

The dist directory is a build artefact and is gitignored, so these tests
build a minimal stand-in with the same SHAPE (index.html + assets/) rather
than depending on `npm run build` having been run. What is under test is the
serving contract, not the bundle's contents.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from mcma.app.frontend import SPA_ROUTES, FrontendBuildMissing, mount_frontend
from mcma.app.security_headers import CONTENT_SECURITY_POLICY


@pytest.fixture()
def dist(tmp_path):
    root = tmp_path / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text(
        '<!doctype html><html lang="fr"><head>'
        '<script type="module" crossorigin src="/assets/index-abc123.js"></script>'
        '<link rel="stylesheet" crossorigin href="/assets/style-abc123.css">'
        "</head><body><div id=\"root\"></div></body></html>",
        encoding="utf-8",
    )
    (root / "assets" / "index-abc123.js").write_text("export {};", encoding="utf-8")
    (root / "assets" / "style-abc123.css").write_text(":root{}", encoding="utf-8")
    return root


def _app(dist):
    app = FastAPI()

    # Stand-ins for the real API routes, registered first exactly as
    # create_api_app() does in the composition root.
    @app.get("/accounts")
    def accounts():
        return {"accounts": []}

    @app.get("/jobs")
    def jobs():
        return {"jobs": []}

    @app.get("/events")
    def events():
        return {"stream": "placeholder"}

    @app.get("/health")
    def health():
        return {"status": "ok"}

    mount_frontend(app, dist_dir=dist)
    return app


def test_every_declared_spa_route_serves_the_built_index(dist):
    client = TestClient(_app(dist))
    addresses = [
        "/",
        "/overview",
        "/accounts/acct-1/work",
        "/accounts/acct-1/work/claim-1",
        "/accounts/acct-1/agent",
        "/accounts/acct-1/agent/runs/job-1",
    ]
    assert len(addresses) == len(SPA_ROUTES)
    for address in addresses:
        response = client.get(address)
        assert response.status_code == 200, address
        assert 'id="root"' in response.text, address


def test_index_responses_carry_the_security_headers(dist):
    """A deep-link reload must be as protected as the root document: the
    header, not the meta tag, is what makes frame-ancestors real."""
    client = TestClient(_app(dist))
    for address in ("/", "/accounts/acct-1/agent/runs/job-1"):
        response = client.get(address)
        assert response.headers["content-security-policy"] == CONTENT_SECURITY_POLICY
        assert response.headers["x-frame-options"] == "DENY"
        assert response.headers["cache-control"] == "no-store"


def test_api_routes_still_win_over_the_spa(dist):
    client = TestClient(_app(dist))
    for address in ("/accounts", "/jobs", "/events", "/health"):
        response = client.get(address)
        assert response.status_code == 200, address
        assert "application/json" in response.headers["content-type"], address
        assert 'id="root"' not in response.text, address


def test_the_sse_endpoint_is_not_swallowed_by_the_spa(dist):
    """/events must stay a backend route. If the SPA ever answered it, the
    EventSource would receive HTML and the UI would silently stop updating."""
    client = TestClient(_app(dist))
    response = client.get("/events")
    assert response.status_code == 200
    assert response.json() == {"stream": "placeholder"}


def test_unknown_backend_paths_stay_backend_404s(dist):
    """The reason there is no catch-all: a mistyped API path must not become
    an HTML 200 that looks like it worked."""
    client = TestClient(_app(dist))
    for address in ("/jobs/typo", "/events/whatever", "/auth/typo", "/bootstrap-app/typo"):
        response = client.get(address)
        assert response.status_code in (404, 405), address
        assert 'id="root"' not in response.text, address


def test_an_undeclared_frontend_path_is_a_404_not_a_silent_index(dist):
    """The documented cost of registering SPA routes explicitly: a typed
    address that is not a declared route is a backend 404 rather than the
    React not-found screen. Pinned so the trade-off stays visible, and so
    that adding a route to the React router without adding it here fails
    here rather than in production."""
    client = TestClient(_app(dist))
    for address in ("/overviewx", "/accounts/acct-1/workx", "/accounts"):
        response = client.get(address)
        assert 'id="root"' not in response.text, address


def test_only_hashed_assets_are_served(dist):
    """Nothing outside dist/assets is reachable, and index.html has no
    second, header-less copy the way the old dashboard once did."""
    client = TestClient(_app(dist))
    assert client.get("/assets/index-abc123.js").status_code == 200
    assert client.get("/index.html").status_code == 404
    assert client.get("/assets/../index.html").status_code in (404, 400)
    assert client.get("/assets/%2e%2e/index.html").status_code in (404, 400)


def test_a_missing_build_refuses_to_mount(tmp_path):
    """An install whose UI was never built fails at startup with a sentence
    naming the fix, instead of serving 500s to an employee."""
    with pytest.raises(FrontendBuildMissing):
        mount_frontend(FastAPI(), dist_dir=tmp_path / "absent")


def test_the_csp_forbids_inline_and_external_sources():
    for forbidden in ("unsafe-inline", "unsafe-eval", "data:", "http://", "https://"):
        assert forbidden not in CONTENT_SECURITY_POLICY
    for required in ("default-src 'self'", "frame-ancestors 'none'", "base-uri 'none'"):
        assert required in CONTENT_SECURITY_POLICY
