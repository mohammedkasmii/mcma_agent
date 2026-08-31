"""
mcma.app.dashboard -- mounts the hardened vanilla-JS dashboard (INC-19)
onto an existing authenticated API app. Kept separate from
mcma.app.api.app.create_api_app() so the API remains testable/deployable
on its own -- a caller that wants the dashboard calls mount_dashboard()
explicitly (the real mcma.app.serve startup sequence does).

`mcma/web/` is plain static assets (HTML/CSS/JS) with no Python import
graph -- there is nothing here for import-linter's layering to check
beyond this module itself, which imports only fastapi (already
mcma.app's own allowed import).
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

_WEB_DIR = Path(__file__).resolve().parent.parent / "web"

# CSP set as a real response HEADER (not only the <meta> tag baked into
# index.html) -- frame-ancestors in particular is HTTP-header-only per
# spec. No inline script/style is ever allowed (script-src/style-src
# 'self' only) -- every script in mcma/web/*.js is an external file.
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self'; style-src 'self'; "
    "connect-src 'self'; img-src 'self'; frame-ancestors 'none'; "
    "base-uri 'none'; form-action 'self'"
)


def mount_dashboard(app: FastAPI, *, web_dir: Path = _WEB_DIR) -> None:
    """Serves mcma/web/index.html at GET / (with the CSP header) and
    ONLY mcma/web/static/ (app.js, style.css) at /static/*.

    Fable-review-2 correction: index.html previously lived in the SAME
    directory StaticFiles served, so the identical document was also
    reachable at /static/index.html with no CSP header at all (the
    `<meta>` tag's `frame-ancestors` is ignored per spec, so that copy
    was framable -- a clickjacking surface on the "Review completed"/
    "Problem" buttons). index.html now lives OUTSIDE the directory this
    mount serves, so /static/index.html is a plain 404, not a second,
    unprotected copy of the dashboard."""

    @app.get("/")
    def dashboard_index():
        response = FileResponse(web_dir / "index.html")
        response.headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
        response.headers["X-Frame-Options"] = "DENY"
        return response

    app.mount("/static", StaticFiles(directory=str(web_dir / "static")), name="static")
