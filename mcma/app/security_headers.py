"""
mcma.app.security_headers -- the one definition of the response security
policy served with any HTML document this application returns.

Extracted so the employee UI (mcma.app.frontend) and the retired vanilla
dashboard (mcma.app.dashboard) cannot drift apart: two copies of a CSP is
how one of them quietly loosens. The policy itself is unchanged from the
one INC-19 introduced.

No 'unsafe-inline', no 'unsafe-eval', no data:, no external origin. The
Vite build is configured to satisfy exactly this (assetsInlineLimit 0,
cssCodeSplit false, modulePreload polyfill disabled), and
frontend/scripts/audit-build.mjs fails the build if it ever stops doing so.
"""

from __future__ import annotations

CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self'; style-src 'self'; "
    "connect-src 'self'; img-src 'self'; frame-ancestors 'none'; "
    "base-uri 'none'; form-action 'self'"
)
