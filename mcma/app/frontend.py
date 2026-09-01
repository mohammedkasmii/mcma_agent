"""
mcma.app.frontend -- serves the built Frontend V2 (frontend/dist) from the
same authenticated origin as the API.

Kept separate from mcma.app.api.app.create_api_app() for the same reason
mcma.app.dashboard was: the API stays testable and deployable on its own,
and a caller that wants the employee UI mounts it explicitly. This module
imports only fastapi and pathlib, so import-linter's layering has nothing
new to check.

WHY NOT A CATCH-ALL. The obvious way to make BrowserRouter deep links work
is a `/{full_path:path}` route returning index.html. That would turn every
typo under /jobs, /auth or /events into an HTML 200, which is worse than a
broken link: a client (or a person reading a curl output) cannot tell a
mistyped API path from a working one, and a 200 for /auth/typo is a
genuinely misleading answer about an authentication endpoint. So the SPA
routes are registered EXPLICITLY, one per route the React router actually
declares. An address that is neither a real API route nor a declared
frontend route stays a backend 404.

The cost of that choice is that an unknown frontend path -- /overviewx --
is a FastAPI 404 rather than the React "Page introuvable" screen. The
React NotFound route still catches client-side navigation to an unknown
path; only a typed/pasted unknown URL differs. That is the safer side to
err on, and it is the reason this file lists routes instead of globbing.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from mcma.app.security_headers import CONTENT_SECURITY_POLICY

_DIST_DIR = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"

# One entry per path in frontend/src/shared/utils/routes.ts. A route added
# there without being added here deep-links to a 404, which is a visible
# failure rather than a silent one.
SPA_ROUTES: tuple[str, ...] = (
    "/",
    "/overview",
    "/accounts/{account_id}/work",
    "/accounts/{account_id}/work/{claim_pk}",
    "/accounts/{account_id}/agent",
    "/accounts/{account_id}/agent/runs/{job_id}",
)


class FrontendBuildMissing(RuntimeError):
    """Raised at startup, never per request: an install whose UI was never
    built should refuse to start rather than serve 500s to an employee who
    has no way to diagnose them."""


def _index_response(index_path: Path) -> FileResponse:
    response = FileResponse(index_path)
    # Set as real response HEADERS, not only via <meta>: frame-ancestors is
    # header-only per spec, and the index document is the one an attacker
    # would try to frame.
    response.headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
    response.headers["X-Frame-Options"] = "DENY"
    # index.html names hash-stamped asset files. Caching it would keep an
    # employee on the previous build's HTML pointing at assets that no
    # longer exist. The assets themselves are content-hashed and cacheable.
    response.headers["Cache-Control"] = "no-store"
    return response


def mount_frontend(app: FastAPI, *, dist_dir: Path = _DIST_DIR) -> None:
    """Serves frontend/dist/index.html at every declared SPA route (each
    with the CSP and framing headers) and ONLY frontend/dist/assets/ at
    /assets/*.

    /assets is mounted rather than the whole dist directory: dist contains
    index.html, and serving it as static would expose a second copy of the
    document at /index.html with no CSP header -- the same clickjacking
    hole mcma.app.dashboard had to correct. Nothing outside dist/assets is
    reachable, so source files, package manifests, node_modules and
    sourcemaps are not exposed regardless of what a build leaves behind.

    Routes are registered here, after create_api_app() has registered the
    API. FastAPI matches in registration order, so /accounts, /claims,
    /jobs, /events, /auth/* and the rest continue to win; the SPA routes
    below use different path shapes and never shadow them.
    """
    index_path = dist_dir / "index.html"
    assets_dir = dist_dir / "assets"
    if not index_path.is_file() or not assets_dir.is_dir():
        raise FrontendBuildMissing(
            f"no built frontend at {dist_dir} -- run `npm ci && npm run build` in frontend/ "
            "before starting the application"
        )

    for route in SPA_ROUTES:
        # Each closure captures the same index; the path parameters are
        # matched only so the URL shape is recognised. They are never read,
        # never echoed, and never touch the filesystem -- there is no path
        # built from user input here, so no traversal surface.
        app.add_api_route(
            route,
            _make_index_endpoint(index_path),
            methods=["GET"],
            include_in_schema=False,
        )

    app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="frontend-assets")


def _make_index_endpoint(index_path: Path):
    def serve_index() -> FileResponse:
        return _index_response(index_path)

    return serve_index
