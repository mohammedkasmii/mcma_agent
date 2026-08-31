"""INC-16 -- session cookies, idle/absolute expiry, logout, CSRF,
permission enum/role map."""

import time
from datetime import datetime, timedelta, timezone

from fastapi import Response

from mcma.app.auth.csrf import generate_csrf_token, verify_csrf_token
from mcma.app.auth.permissions import Permission, permissions_for_role, role_has_permission
from mcma.app.auth.sessions import SessionStore, set_session_cookie


def test_session_cookie_httponly_samesite_strict():
    response = Response()
    set_session_cookie(response, "tok-1", secure=True)
    cookie_header = response.headers.get("set-cookie")
    assert "HttpOnly" in cookie_header
    assert "samesite=strict" in cookie_header.lower()


def test_session_cookie_secure_attribute():
    response = Response()
    set_session_cookie(response, "tok-1", secure=True)
    assert "Secure" in response.headers.get("set-cookie")


def test_session_idle_and_absolute_expiry():
    store = SessionStore(idle_timeout_seconds=0, absolute_timeout_seconds=3600)
    token = store.create("user-1")
    time.sleep(0.01)
    assert store.validate(token) is None  # idle-expired immediately

    store2 = SessionStore(idle_timeout_seconds=3600, absolute_timeout_seconds=3600)
    token2 = store2.create("user-1")
    # Force absolute expiry by rewriting created_at into the past.
    store2._sessions[token2].created_at = datetime.now(timezone.utc) - timedelta(hours=1)
    assert store2.validate(token2) is None


def test_logout_invalidates_server_session():
    store = SessionStore()
    token = store.create("user-1")
    assert store.validate(token) == "user-1"
    store.invalidate(token)
    assert store.validate(token) is None


def test_csrf_required_on_state_changing_requests():
    token = generate_csrf_token()
    assert verify_csrf_token(token, token) is True
    assert verify_csrf_token(token, "wrong-token") is False
    assert verify_csrf_token(token, None) is False
    assert verify_csrf_token(None, token) is False


def test_permission_enum_values():
    assert {p.value for p in Permission} == {
        "notifications:read", "notifications:update", "jobs:plan", "jobs:execute",
        "jobs:view", "sessions:manage", "accounts:manage", "users:manage",
    }


def test_viewer_role_has_no_mutation_permission():
    mutation_permissions = {
        Permission.NOTIFICATIONS_UPDATE, Permission.JOBS_PLAN, Permission.JOBS_EXECUTE,
        Permission.SESSIONS_MANAGE, Permission.ACCOUNTS_MANAGE, Permission.USERS_MANAGE,
    }
    viewer_permissions = permissions_for_role("viewer")
    assert viewer_permissions.isdisjoint(mutation_permissions)
    assert role_has_permission("viewer", Permission.JOBS_EXECUTE) is False
    assert role_has_permission("admin", Permission.JOBS_EXECUTE) is True
