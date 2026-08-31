"""
mcma.app.auth.csrf -- CSRF token issuance/verification (INC-16,
API_CONTRACTS.md §3). Double-submit-cookie style: the token is handed to
the client (e.g. as a separate readable cookie or response field) and
must be echoed back in a request header on every state-changing request;
verification uses a constant-time comparison.
"""

from __future__ import annotations

import hmac
import secrets

CSRF_HEADER_NAME = "X-CSRF-Token"
CSRF_COOKIE_NAME = "mcma_csrf"


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def verify_csrf_token(expected: str | None, provided: str | None) -> bool:
    if not expected or not provided:
        return False
    return hmac.compare_digest(expected, provided)
