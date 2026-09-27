"""/auth/me, hardened /auth/logout, cookie attributes, SessionStore
concurrency and the admin-only user-management API."""

import threading

import pytest
from fastapi.testclient import TestClient

from api_test_support import (  # noqa: F401
    MAMDA_NADOR, MAMDA_OUJDA, NADOR, OUJDA, conn, create_user, csrf_headers, db_path, grant_access, login_client,
)
from mcma.app.api.app import create_api_app
from mcma.app.auth.provider import LocalUserAuthProvider
from mcma.app.auth.sessions import IDLE_TIMEOUT_SECONDS, SESSION_COOKIE_NAME, SessionStore
from mcma.execution.inputs import TestOnlyPlaintextEncryptor

PASSWORD = "correct horse battery"
ALL = [OUJDA, NADOR, MAMDA_OUJDA, MAMDA_NADOR]


def _app(conn, store=None, *, secure=True):
    store = store or SessionStore()
    app = create_api_app(conn, auth_provider=LocalUserAuthProvider(conn), session_store=store,
                         encryptor=TestOnlyPlaintextEncryptor(), secure_cookies=secure)
    return TestClient(app, base_url="https://testserver", client=("203.0.113.9", 4000)), store


def _make(conn, username, role, accounts=()):
    uid = create_user(conn, username, PASSWORD, role)
    for account in accounts:
        grant_access(conn, uid, account)
    return uid


@pytest.fixture()
def admin_client(conn):
    _make(conn, "boss", "admin", ALL)
    client, store = _app(conn)
    csrf = login_client(client, "boss", PASSWORD)
    return client, csrf, store


# ------------------------------------ /auth/me -------------------------------------- #


def test_me_returns_only_safe_identity_permissions_and_accounts(conn):
    _make(conn, "sara", "operator", [OUJDA, NADOR])
    client, _ = _app(conn)
    login_client(client, "sara", PASSWORD)
    response = client.get("/auth/me")
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    body = response.json()
    assert set(body) == {"user_id", "username", "role", "permissions", "account_ids", "local_single_user"}
    assert (body["username"], body["role"], body["local_single_user"]) == ("sara", "operator", False)
    assert body["account_ids"] == sorted([OUJDA, NADOR])
    assert "jobs:plan" in body["permissions"] and "users:manage" not in body["permissions"]
    assert "hash" not in response.text and PASSWORD not in response.text and "argon2" not in response.text


def test_admin_permissions_include_user_management(admin_client):
    client, _, _ = admin_client
    assert "users:manage" in client.get("/auth/me").json()["permissions"]


def test_me_is_401_without_a_session_or_with_a_forged_one(conn):
    client, _ = _app(conn)
    assert client.get("/auth/me").status_code == 401
    client.cookies.set(SESSION_COOKIE_NAME, "forged-token")
    assert client.get("/auth/me").status_code == 401


def test_me_is_401_after_the_session_expires(conn):
    _make(conn, "sara", "viewer", [OUJDA])
    client, store = _app(conn, SessionStore(idle_timeout_seconds=0))
    login_client(client, "sara", PASSWORD)
    import time

    time.sleep(0.05)
    assert client.get("/auth/me").status_code == 401


def test_me_rejects_an_inactive_user_even_with_a_live_session(conn):
    uid = _make(conn, "sara", "viewer", [OUJDA])
    client, _ = _app(conn)
    login_client(client, "sara", PASSWORD)
    assert client.get("/auth/me").status_code == 200
    conn.execute("UPDATE users SET active = 0 WHERE user_id = ?", (uid,))
    assert client.get("/auth/me").status_code == 401


def test_an_inactive_user_cannot_log_in(conn):
    uid = _make(conn, "sara", "viewer")
    conn.execute("UPDATE users SET active = 0 WHERE user_id = ?", (uid,))
    client, _ = _app(conn)
    assert client.post("/auth/login", json={"username": "sara", "password": PASSWORD}).status_code == 401


def test_unknown_user_and_wrong_password_are_indistinguishable(conn):
    _make(conn, "sara", "viewer")
    client, _ = _app(conn)
    wrong_pw = client.post("/auth/login", json={"username": "sara", "password": "nope-nope-nope"})
    no_user = client.post("/auth/login", json={"username": "ghost", "password": "nope-nope-nope"})
    strip = lambda r: {k: v for k, v in r.json().items() if k != "correlation_id"}
    assert wrong_pw.status_code == no_user.status_code == 401 and strip(wrong_pw) == strip(no_user)


def test_login_is_case_insensitive_for_the_username(conn):
    _make(conn, "sara", "viewer")
    client, _ = _app(conn)
    assert client.post("/auth/login", json={"username": "  SARA ", "password": PASSWORD}).status_code == 200


# -------------------------------- cookies and logout -------------------------------- #


def _set_cookies(response):
    return {h.split("=", 1)[0]: h for h in response.headers.get_list("set-cookie")}


def test_login_cookies_are_secure_httponly_samesite_strict(conn):
    _make(conn, "sara", "viewer")
    client, _ = _app(conn)
    response = client.post("/auth/login", json={"username": "sara", "password": PASSWORD})
    cookies = _set_cookies(response)
    session, csrf = cookies["mcma_session"].lower(), cookies["mcma_csrf"].lower()
    assert "httponly" in session and "secure" in session and "samesite=strict" in session
    assert "httponly" not in csrf and "secure" in csrf and "samesite=strict" in csrf     # readable by JS, still Secure
    assert response.headers["cache-control"] == "no-store"


def test_logout_requires_csrf_and_keeps_the_session_when_refused(conn):
    _make(conn, "sara", "viewer", [OUJDA])
    client, store = _app(conn)
    csrf = login_client(client, "sara", PASSWORD)
    assert client.post("/auth/logout").status_code == 403
    assert client.post("/auth/logout", headers={"X-CSRF-Token": "wrong"}).status_code == 403
    assert client.get("/auth/me").status_code == 200                       # nothing was invalidated
    assert client.post("/auth/logout", headers=csrf_headers(csrf)).status_code == 200


def test_logout_needs_an_authenticated_session(conn):
    client, _ = _app(conn)
    assert client.post("/auth/logout").status_code in (401, 403)


def test_logout_invalidates_the_server_session_and_clears_both_cookies_identically(conn):
    _make(conn, "sara", "viewer", [OUJDA])
    client, store = _app(conn)
    csrf = login_client(client, "sara", PASSWORD)
    stolen = client.cookies.get(SESSION_COOKIE_NAME)
    response = client.post("/auth/logout", headers=csrf_headers(csrf))
    assert response.status_code == 200 and response.json() == {"status": "logged_out"}
    assert store.validate(stolen) is None                                   # dead server-side, not just in the browser
    cookies = _set_cookies(response)
    assert set(cookies) == {"mcma_session", "mcma_csrf"}
    for name, header in cookies.items():
        lowered = header.lower()
        assert "max-age=0" in lowered and "path=/" in lowered
        assert "secure" in lowered and "samesite=strict" in lowered
    assert "httponly" in cookies["mcma_session"].lower() and "httponly" not in cookies["mcma_csrf"].lower()
    other, _ = _app(conn, store)
    other.cookies.set(SESSION_COOKIE_NAME, stolen)
    assert other.get("/auth/me").status_code == 401                         # replaying the old token fails


# ------------------------------- SessionStore ---------------------------------------- #


def test_session_store_survives_concurrent_use():
    store = SessionStore()
    errors, tokens = [], []
    barrier = threading.Barrier(12)

    def worker(index):
        try:
            barrier.wait()
            for round_ in range(300):
                token = store.create(f"user-{index}")
                assert store.validate(token) == f"user-{index}"
                if round_ % 3 == 0:
                    store.invalidate(token)
                    assert store.validate(token) is None
                else:
                    tokens.append(token)
                store.validate("unknown-token")
        except BaseException as exc:                      # noqa: BLE001 - surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert all(store.validate(t) is not None for t in tokens[:200])


def test_expiry_and_invalidation_race_without_errors():
    store = SessionStore(idle_timeout_seconds=0)
    errors = []

    def churn():
        try:
            for _ in range(400):
                token = store.create("u")
                store.validate(token)       # may delete an expired entry
                store.invalidate(token)     # may find it already gone
                store.invalidate_user("u")
        except BaseException as exc:        # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=churn) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []


def test_invalidate_user_drops_only_that_users_sessions():
    store = SessionStore()
    a1, a2, b1 = store.create("a"), store.create("a"), store.create("b")
    assert store.invalidate_user("a") == 2
    assert store.validate(a1) is None and store.validate(a2) is None and store.validate(b1) == "b"


def test_idle_timeout_constant_is_unchanged():
    assert IDLE_TIMEOUT_SECONDS == 30 * 60


# --------------------------------- admin API -------------------------------------------- #


def _new_user(client, csrf, **overrides):
    body = {"username": "sara", "password": PASSWORD, "role": "operator", "account_ids": [OUJDA]}
    body.update(overrides)
    return client.post("/admin/users", json=body, headers=csrf_headers(csrf))


def test_admin_creates_lists_and_the_new_user_can_log_in(admin_client, conn):
    client, csrf, store = admin_client
    created = _new_user(client, csrf, username="Sara", account_ids=[OUJDA, NADOR])
    assert created.status_code == 201 and created.headers["cache-control"] == "no-store"
    user = created.json()["user"]
    assert (user["username"], user["role"], user["active"]) == ("sara", "operator", True)
    assert user["account_ids"] == sorted([OUJDA, NADOR]) and set(user) == {"user_id", "username", "role", "active", "account_ids"}
    listing = client.get("/admin/users")
    assert listing.status_code == 200 and [u["username"] for u in listing.json()["users"]] == ["boss", "sara"]
    employee, _ = _app(conn, store)
    assert employee.post("/auth/login", json={"username": "sara", "password": PASSWORD}).status_code == 200
    assert employee.get("/auth/me").json()["account_ids"] == sorted([OUJDA, NADOR])


def test_passwords_and_hashes_never_appear_in_any_admin_response(admin_client):
    client, csrf, _ = admin_client
    secret = "another long secret phrase"
    responses = [
        _new_user(client, csrf, password=secret), client.get("/admin/users"),
        _new_user(client, csrf, username="dup", password="x"),          # validation error
        _new_user(client, csrf, password=secret),                       # duplicate
    ]
    uid = responses[0].json()["user"]["user_id"]
    responses.append(client.post(f"/admin/users/{uid}/password", json={"password": secret + "!"}, headers=csrf_headers(csrf)))
    responses.append(client.patch(f"/admin/users/{uid}", json={"active": False}, headers=csrf_headers(csrf)))
    for response in responses:
        text = response.text
        assert secret not in text and "argon2" not in text and "password_hash" not in text


def test_every_mutating_admin_endpoint_requires_csrf(admin_client):
    client, csrf, _ = admin_client
    uid = _new_user(client, csrf).json()["user"]["user_id"]
    assert client.post("/admin/users", json={"username": "x1x", "password": PASSWORD, "role": "viewer"}).status_code == 403
    assert client.patch(f"/admin/users/{uid}", json={"active": False}).status_code == 403
    assert client.post(f"/admin/users/{uid}/password", json={"password": PASSWORD + "z"}).status_code == 403
    assert client.get("/admin/users").status_code == 200                # reads need no CSRF
    assert len(client.get("/admin/users").json()["users"]) == 2         # nothing changed


@pytest.mark.parametrize("role", ["operator", "viewer"])
def test_operators_and_viewers_are_forbidden_from_user_management(conn, role):
    uid = _make(conn, "emp", role, ALL)
    _make(conn, "boss", "admin", ALL)
    client, _ = _app(conn)
    csrf = login_client(client, "emp", PASSWORD)
    target = conn.execute("SELECT user_id FROM users WHERE username = 'boss'").fetchone()["user_id"]
    calls = [
        client.get("/admin/users"),
        client.post("/admin/users", json={"username": "abc", "password": PASSWORD, "role": "admin"}, headers=csrf_headers(csrf)),
        client.patch(f"/admin/users/{target}", json={"active": False}, headers=csrf_headers(csrf)),
        client.post(f"/admin/users/{target}/password", json={"password": PASSWORD + "z"}, headers=csrf_headers(csrf)),
    ]
    assert [c.status_code for c in calls] == [403, 403, 403, 403]
    assert conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"] == 2
    assert conn.execute("SELECT active, role FROM users WHERE user_id = ?", (target,)).fetchone()["active"] == 1
    assert uid


def test_unauthenticated_requests_to_admin_endpoints_are_401(conn):
    client, _ = _app(conn)
    assert client.get("/admin/users").status_code == 401
    assert client.post("/admin/users", json={}).status_code in (401, 403)


def test_an_operator_cannot_escalate_themselves_to_admin(conn):
    uid = _make(conn, "emp", "operator", ALL)
    client, _ = _app(conn)
    csrf = login_client(client, "emp", PASSWORD)
    r = client.patch(f"/admin/users/{uid}", json={"role": "admin"}, headers=csrf_headers(csrf))
    assert r.status_code == 403
    assert conn.execute("SELECT role FROM users WHERE user_id = ?", (uid,)).fetchone()["role"] == "operator"


@pytest.mark.parametrize("override, code", [
    ({"username": "x"}, "USERNAME_INVALID"), ({"password": "short"}, "PASSWORD_TOO_SHORT"),
    ({"password": "sara-sara-sara-sara"}, "PASSWORD_CONTAINS_USERNAME"), ({"role": "root"}, "ROLE_INVALID"),
    ({"account_ids": ["acct-nope"]}, "ACCOUNT_UNKNOWN"), ({"account_ids": "acct-mcma-oujda"}, "ACCOUNT_UNKNOWN"),
])
def test_creation_validation_errors_have_stable_codes(admin_client, override, code):
    client, csrf, _ = admin_client
    response = _new_user(client, csrf, **override)
    assert response.status_code == 400 and response.json()["error"] == code
    assert len(client.get("/admin/users").json()["users"]) == 1


def test_duplicate_usernames_conflict_case_insensitively(admin_client):
    client, csrf, _ = admin_client
    assert _new_user(client, csrf).status_code == 201
    for variant in ("sara", "SARA", "Sara "):
        response = _new_user(client, csrf, username=variant)
        assert response.status_code == 409 and response.json()["error"] == "USERNAME_TAKEN"


def test_the_acting_admin_comes_from_the_session_not_the_request(admin_client, conn):
    client, csrf, _ = admin_client
    response = client.post("/admin/users", json={"username": "sara", "password": PASSWORD, "role": "viewer",
                                                  "account_ids": [], "actor_user_id": "forged", "created_by": "forged"},
                           headers=csrf_headers(csrf))
    assert response.status_code == 201
    boss = conn.execute("SELECT user_id FROM users WHERE username = 'boss'").fetchone()["user_id"]
    audit = conn.execute("SELECT actor_user_id FROM audit_events WHERE action = 'user.created'").fetchone()
    assert audit["actor_user_id"] == boss


def test_patch_rejects_unknown_fields_and_empty_bodies(admin_client):
    client, csrf, _ = admin_client
    uid = _new_user(client, csrf).json()["user"]["user_id"]
    for body in ({}, {"password": "x"}, {"username": "renamed"}, {"active": "yes"}):
        assert client.patch(f"/admin/users/{uid}", json=body, headers=csrf_headers(csrf)).status_code == 400
    assert client.patch("/admin/users/nope", json={"active": False}, headers=csrf_headers(csrf)).status_code == 404


def test_account_assignment_is_validated_and_replaces_the_set(admin_client):
    client, csrf, _ = admin_client
    uid = _new_user(client, csrf, account_ids=[OUJDA]).json()["user"]["user_id"]
    ok = client.patch(f"/admin/users/{uid}", json={"account_ids": [NADOR, MAMDA_NADOR]}, headers=csrf_headers(csrf))
    assert ok.json()["user"]["account_ids"] == sorted([NADOR, MAMDA_NADOR])
    bad = client.patch(f"/admin/users/{uid}", json={"account_ids": [NADOR, "acct-other"]}, headers=csrf_headers(csrf))
    assert bad.status_code == 400 and bad.json()["error"] == "ACCOUNT_UNKNOWN"
    assert [u for u in client.get("/admin/users").json()["users"] if u["user_id"] == uid][0]["account_ids"] == sorted([NADOR, MAMDA_NADOR])


def test_deactivation_ends_the_users_sessions_and_reactivation_restores_login(admin_client, conn):
    client, csrf, store = admin_client
    uid = _new_user(client, csrf).json()["user"]["user_id"]
    employee, _ = _app(conn, store)
    login_client(employee, "sara", PASSWORD)
    assert employee.get("/auth/me").status_code == 200
    assert client.patch(f"/admin/users/{uid}", json={"active": False}, headers=csrf_headers(csrf)).json()["user"]["active"] is False
    assert employee.get("/auth/me").status_code == 401
    assert employee.post("/auth/login", json={"username": "sara", "password": PASSWORD}).status_code == 401
    client.patch(f"/admin/users/{uid}", json={"active": True}, headers=csrf_headers(csrf))
    assert employee.post("/auth/login", json={"username": "sara", "password": PASSWORD}).status_code == 200


def test_password_reset_changes_the_password_and_ends_old_sessions(admin_client, conn):
    client, csrf, store = admin_client
    uid = _new_user(client, csrf).json()["user"]["user_id"]
    employee, _ = _app(conn, store)
    login_client(employee, "sara", PASSWORD)
    new_password = "brand new passphrase"
    r = client.post(f"/admin/users/{uid}/password", json={"password": new_password}, headers=csrf_headers(csrf))
    assert r.status_code == 200 and r.json() == {"status": "password_reset"}
    assert employee.get("/auth/me").status_code == 401                        # old sessions are gone
    assert employee.post("/auth/login", json={"username": "sara", "password": PASSWORD}).status_code == 401
    assert employee.post("/auth/login", json={"username": "sara", "password": new_password}).status_code == 200
    weak = client.post(f"/admin/users/{uid}/password", json={"password": "short"}, headers=csrf_headers(csrf))
    assert weak.status_code == 400 and weak.json()["error"] == "PASSWORD_TOO_SHORT"


def test_admin_cannot_lock_themselves_out_or_remove_the_last_admin(admin_client, conn):
    client, csrf, _ = admin_client
    boss = conn.execute("SELECT user_id FROM users WHERE username = 'boss'").fetchone()["user_id"]
    for body in ({"active": False}, {"role": "viewer"}):
        r = client.patch(f"/admin/users/{boss}", json=body, headers=csrf_headers(csrf))
        assert r.status_code == 409 and r.json()["error"] in ("SELF_LOCKOUT", "LAST_ADMIN")
    assert client.get("/auth/me").status_code == 200
    assert conn.execute("SELECT active, role FROM users WHERE user_id = ?", (boss,)).fetchone()["role"] == "admin"


def test_the_admin_api_never_touches_portal_credentials_or_sessions(admin_client, conn):
    client, csrf, _ = admin_client
    before = {t: conn.execute(f"SELECT COUNT(*) AS c FROM {t}").fetchone()["c"] for t in ("accounts", "portal_sessions")}
    uid = _new_user(client, csrf, account_ids=ALL).json()["user"]["user_id"]
    client.patch(f"/admin/users/{uid}", json={"active": False}, headers=csrf_headers(csrf))
    client.post(f"/admin/users/{uid}/password", json={"password": "yet another passphrase"}, headers=csrf_headers(csrf))
    after = {t: conn.execute(f"SELECT COUNT(*) AS c FROM {t}").fetchone()["c"] for t in ("accounts", "portal_sessions")}
    assert after == before
