"""HTTP surface of the notification-onboarding control plane: browser routes
(cookie session + CSRF) and runner machine routes (bearer only). Loopback /
TestClient only; the real portal is never contacted."""

import json
import logging

import pytest
from fastapi.testclient import TestClient

from api_test_support import (  # noqa: F401
    MAMDA_NADOR, MAMDA_OUJDA, NADOR, OUJDA, conn, create_user, csrf_headers, db_path, grant_access, login_client,
)
from mcma.app.api.app import create_api_app
from mcma.app.auth.provider import LocalUserAuthProvider
from mcma.app.auth.sessions import SessionStore
from mcma.app.connection_state import ConnectionStateTracker
from mcma.app.runners import notification_onboarding as onb
from mcma.execution.inputs import TestOnlyPlaintextEncryptor
from mcma.persistence.db import open_database
from mcma.portal.vault import AesGcmSessionVaultBackend, TestOnlyAclVerifier, load_and_verify_session

PASSWORD = "correct horse battery"
ALL = [OUJDA, NADOR, MAMDA_OUJDA, MAMDA_NADOR]
MARKER = "HTTP-COOKIE-MARKER-77d1"
CLAIM = "/runner/notification-onboarding/claim"


def good_state(value=MARKER):
    return {"cookies": [{"name": "sid", "value": value, "domain": "sinauto.mamda-mcma.ma", "path": "/", "expires": -1,
                         "httpOnly": True, "secure": True, "sameSite": "Lax"}], "origins": []}


def client(app):
    return TestClient(app, base_url="https://testserver", client=("203.0.113.9", 4000))


@pytest.fixture()
def world(conn, tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    tracker = ConnectionStateTracker()
    backend = AesGcmSessionVaultBackend(b"z" * 32)
    service = onb.NotificationOnboardingService(
        conn, vault_dir=vault, instance_id="central", crypto_backend=backend, acl_verifier=TestOnlyAclVerifier(True),
        portal_host="sinauto.mamda-mcma.ma", connection_tracker=tracker,
    )
    app = create_api_app(
        conn, auth_provider=LocalUserAuthProvider(conn), session_store=SessionStore(),
        encryptor=TestOnlyPlaintextEncryptor(), secure_cookies=True, runner_registry=True,
        notification_onboarding=service, connection_state_tracker=tracker,
        dry_run_creation_available=True, execute_creation_available=False,
    )
    admin_id = create_user(conn, "boss", PASSWORD, "admin")
    emp = create_user(conn, "emp", PASSWORD, "operator")
    for account in ALL:
        grant_access(conn, admin_id, account)
        grant_access(conn, emp, account)
    boss = client(app)
    boss_csrf = login_client(boss, "boss", PASSWORD)
    code = boss.post("/admin/runner-enrollments", json={"target_user_id": emp}, headers=csrf_headers(boss_csrf)).json()["pairing_code"]
    enrolled = client(app).post("/runner/enroll", json={"pairing_code": code, "protocol_version": 1, "app_version": "0.1.0"}).json()
    secret = enrolled["runner_secret"]
    machine = client(app)
    hb = machine.post("/runner/heartbeat", headers={"Authorization": f"Bearer {secret}"},
                      json={"protocol_version": 1, "app_version": "0.1.0", "sessions": []})
    assert hb.status_code == 200, hb.text
    employee = client(app)
    csrf = login_client(employee, "emp", PASSWORD)
    return dict(conn=conn, app=app, employee=employee, csrf=csrf, secret=secret, vault=vault, backend=backend,
                tracker=tracker, db_path=None, emp=emp, service=service)


def bearer(w):
    return {"Authorization": f"Bearer {w['secret']}"}


def click(w, account=OUJDA, **kwargs):
    headers = {**csrf_headers(w["csrf"]), **kwargs.pop("headers", {})}
    return w["employee"].post(f"/accounts/{account}/login", headers=headers, **kwargs)


def machine(w):
    return client(w["app"])           # a fresh client: no cookies at all


def claim(w):
    return machine(w).post(CLAIM, headers=bearer(w), json={"protocol_version": 1, "app_version": "0.1.0"})


def path(env, action):
    return f"/runner/notification-onboarding/{env['request_id']}/{action}"


def creds(env, **extra):
    return {"claim_token": env["claim_token"], "generation": env["generation"], **extra}


# --------------------------------------------------------------------- #
# browser routes
# --------------------------------------------------------------------- #


def test_click_queues_a_request_and_returns_fast_with_202(world):
    response = click(world)
    assert response.status_code == 202
    body = response.json()
    assert set(body) == {"account_id", "request_id", "state", "outcome_code", "cancel_requested", "expires_at", "updated_at"}
    assert body["state"] == "QUEUED" and body["account_id"] == OUJDA
    assert response.headers["cache-control"] == "no-store"


def test_second_click_returns_the_same_request_with_200(world):
    first = click(world).json()
    second = click(world)
    assert second.status_code == 200 and second.json()["request_id"] == first["request_id"]


@pytest.mark.parametrize("account", ALL)
def test_all_four_accounts_accepted(world, account):
    assert click(world, account).status_code == 202


def test_unauthenticated_click_is_401(world):
    assert client(world["app"]).post(f"/accounts/{OUJDA}/login").status_code == 401


def test_click_without_csrf_is_refused_and_creates_nothing(world):
    assert world["employee"].post(f"/accounts/{OUJDA}/login").status_code == 403
    assert world["conn"].execute("SELECT COUNT(*) FROM notification_onboarding_requests").fetchone()[0] == 0


def test_account_without_access_is_403(world):
    outsider = create_user(world["conn"], "out", PASSWORD, "operator")
    grant_access(world["conn"], outsider, NADOR)
    c = client(world["app"])
    csrf = login_client(c, "out", PASSWORD)
    assert c.post(f"/accounts/{OUJDA}/login", headers=csrf_headers(csrf)).status_code == 403


def test_non_canonical_account_is_refused(world):
    response = click(world, "acct-evil")
    assert response.status_code in (403, 404)
    assert world["conn"].execute("SELECT COUNT(*) FROM notification_onboarding_requests").fetchone()[0] == 0


def test_viewer_without_runner_gets_a_specific_refusal(world):
    viewer = create_user(world["conn"], "view", PASSWORD, "viewer")
    grant_access(world["conn"], viewer, OUJDA)
    c = client(world["app"])
    csrf = login_client(c, "view", PASSWORD)
    response = c.post(f"/accounts/{OUJDA}/login", headers=csrf_headers(csrf))
    assert response.status_code == 409 and response.json()["error"] == "RUNNER_MISSING"


def test_offline_runner_is_refused_specifically(world):
    world["conn"].execute("UPDATE runners SET last_seen_at = '2020-01-01T00:00:00+00:00'")
    response = click(world)
    assert response.status_code == 409 and response.json()["error"] == "RUNNER_OFFLINE"


@pytest.mark.parametrize("body", [
    {"runner_id": "x"}, {"user_id": "x"}, {"entity": "MCMA"}, {"scope": "OUJDA"}, {"server": "https://evil"},
    {"url": "https://evil"}, {"username": "u", "password": "p"}, {"otp": "123456"}, {"x": 1},
])
def test_browser_cannot_supply_anything(world, body):
    response = click(world, json=body)
    assert response.status_code == 400
    assert world["conn"].execute("SELECT COUNT(*) FROM notification_onboarding_requests").fetchone()[0] == 0


def test_empty_object_body_is_accepted(world):
    assert click(world, json={}).status_code == 202


def test_oversized_body_fails_closed(world):
    response = click(world, content=b"{" + b" " * 5000 + b"}", headers={"content-type": "application/json"})
    assert response.status_code == 413


def test_malformed_body_fails_closed(world):
    response = world["employee"].post(f"/accounts/{OUJDA}/login", content=b"[1,2]",
                                      headers={**csrf_headers(world["csrf"]), "content-type": "application/json"})
    assert response.status_code == 400


def test_status_endpoint_reports_progress(world):
    assert world["employee"].get(f"/accounts/{OUJDA}/login-status").json()["state"] == "IDLE"
    click(world)
    status = world["employee"].get(f"/accounts/{OUJDA}/login-status")
    assert status.status_code == 200 and status.json()["state"] == "QUEUED"
    assert status.headers["cache-control"] == "no-store"
    env = claim(world).json()
    machine(world).post(path(env, "renew"), headers=bearer(world), json=creds(env, phase="WINDOW_OPENED"))
    assert world["employee"].get(f"/accounts/{OUJDA}/login-status").json()["state"] == "WINDOW_OPENED"
    machine(world).post(path(env, "renew"), headers=bearer(world), json=creds(env, phase="WAITING_FOR_LOGIN"))
    assert world["employee"].get(f"/accounts/{OUJDA}/login-status").json()["state"] == "WAITING_FOR_LOGIN"


def test_status_requires_auth_and_account_access(world):
    assert client(world["app"]).get(f"/accounts/{OUJDA}/login-status").status_code == 401
    outsider = create_user(world["conn"], "out2", PASSWORD, "operator")
    grant_access(world["conn"], outsider, NADOR)
    c = client(world["app"])
    login_client(c, "out2", PASSWORD)
    assert c.get(f"/accounts/{OUJDA}/login-status").status_code == 403


def test_status_never_leaks_internals(world):
    click(world)
    env = claim(world).json()
    text = world["employee"].get(f"/accounts/{OUJDA}/login-status").text
    assert env["claim_token"] not in text and world["secret"] not in text
    for banned in ("session", "token", "runner", "digest", "path"):
        assert banned not in text.lower().replace("request_id", "")


def test_cancel_is_idempotent_and_csrf_protected(world):
    click(world)
    assert world["employee"].post(f"/accounts/{OUJDA}/login/cancel").status_code == 403
    first = world["employee"].post(f"/accounts/{OUJDA}/login/cancel", headers=csrf_headers(world["csrf"]))
    second = world["employee"].post(f"/accounts/{OUJDA}/login/cancel", headers=csrf_headers(world["csrf"]))
    assert first.status_code == second.status_code == 200
    assert first.json()["state"] == second.json()["state"] == "CANCELLED"


def test_central_mode_has_no_synchronous_login_and_a_local_opener_conflicts(conn, tmp_path):
    with pytest.raises(ValueError):
        create_api_app(conn, auth_provider=LocalUserAuthProvider(conn), encryptor=TestOnlyPlaintextEncryptor(),
                       portal_login_opener=lambda a: None, notification_onboarding=object())


# --------------------------------------------------------------------- #
# machine routes
# --------------------------------------------------------------------- #


def test_machine_routes_need_a_runner_bearer(world):
    click(world)
    assert machine(world).post(CLAIM, json={"protocol_version": 1, "app_version": "0.1"}).status_code == 401
    assert machine(world).post(CLAIM, headers={"Authorization": "Bearer mcma_rs_nope"},
                               json={"protocol_version": 1, "app_version": "0.1"}).status_code == 401
    # an employee session cookie is NOT a runner credential
    assert world["employee"].post(CLAIM, json={"protocol_version": 1, "app_version": "0.1"}).status_code == 401


def test_runner_secret_in_query_string_or_body_is_not_accepted(world):
    click(world)
    assert machine(world).post(f"{CLAIM}?token={world['secret']}", json={"protocol_version": 1, "app_version": "0.1"}).status_code == 401


def test_claim_is_204_when_nothing_is_pending(world):
    response = claim(world)
    assert response.status_code == 204 and response.headers["cache-control"] == "no-store"


def test_claim_returns_closed_envelope(world):
    click(world, MAMDA_NADOR)
    response = claim(world)
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    body = response.json()
    assert set(body) == {"request_id", "account_id", "generation", "claim_token", "lease_expires_at", "expires_at", "server_time"}
    assert body["account_id"] == MAMDA_NADOR
    assert claim(world).status_code == 204


@pytest.mark.parametrize("body", [{}, {"protocol_version": 1}, {"protocol_version": 1, "app_version": "1", "account_id": OUJDA},
                                  {"protocol_version": 1, "app_version": "1", "request_id": "x"}])
def test_claim_body_is_strict(world, body):
    assert machine(world).post(CLAIM, headers=bearer(world), json=body).status_code == 400


@pytest.mark.parametrize("action,extra", [("renew", {"phase": "WINDOW_OPENED"}), ("fail", {"reason_code": "INTERNAL_ERROR"})])
def test_lifecycle_bodies_are_strict(world, action, extra):
    click(world)
    env = claim(world).json()
    post = lambda body: machine(world).post(path(env, action), headers=bearer(world), json=body)
    assert post({**creds(env, **extra), "status": "SUCCEEDED"}).status_code == 400
    assert post({"generation": env["generation"], **extra}).status_code == 400
    assert post(creds(env, **extra)).status_code == 200


def test_small_endpoints_have_a_small_body_limit(world):
    click(world)
    env = claim(world).json()
    response = machine(world).post(path(env, "renew"), headers=bearer(world),
                                   json=creds(env, phase="WINDOW_OPENED", pad="x" * 6000))
    assert response.status_code == 413


def test_renew_reports_cancel_request(world):
    click(world)
    env = claim(world).json()
    world["employee"].post(f"/accounts/{OUJDA}/login/cancel", headers=csrf_headers(world["csrf"]))
    body = machine(world).post(path(env, "renew"), headers=bearer(world), json=creds(env, phase="WAITING_FOR_LOGIN")).json()
    assert body["cancel_requested"] is True and set(body) == {"lease_expires_at", "server_time", "cancel_requested"}


def test_wrong_claim_is_one_fixed_404(world):
    click(world)
    env = claim(world).json()
    response = machine(world).post(path(env, "renew"), headers=bearer(world),
                                   json={"claim_token": "mcma_ot_wrong", "generation": 1, "phase": "WINDOW_OPENED"})
    assert response.status_code == 404 and response.json()["error"] == "CLAIM_NOT_FOUND"
    assert machine(world).post("/runner/notification-onboarding/" + "0" * 32 + "/renew", headers=bearer(world),
                               json=creds(env, phase="WINDOW_OPENED")).status_code == 404


def full_login(world, account=OUJDA, state=None):
    click(world, account)
    env = claim(world).json()
    machine(world).post(path(env, "renew"), headers=bearer(world), json=creds(env, phase="WAITING_FOR_LOGIN"))
    response = machine(world).post(path(env, "complete"), headers=bearer(world),
                                   json=creds(env, storage_state=good_state() if state is None else state))
    return env, response


def test_end_to_end_fake_manual_login_stores_encrypted_session_and_connects(world):
    env, response = full_login(world, MAMDA_OUJDA)
    assert response.status_code == 200 and response.json()["status"] == "SUCCEEDED"
    assert response.headers["cache-control"] == "no-store"
    status = world["employee"].get(f"/accounts/{MAMDA_OUJDA}/login-status").json()
    assert status["state"] == "SUCCEEDED" and status["outcome_code"] == "SESSION_STORED"
    accounts = {a["account_id"]: a for a in world["employee"].get("/accounts").json()["accounts"]}
    assert accounts[MAMDA_OUJDA]["connection_state"] == "CONNECTED"
    # the headless poller (its own connection, same backend, no restart) can open the stored session
    poller = open_database(world["conn"].execute("PRAGMA database_list").fetchone()[2])
    try:
        stored = json.loads(load_and_verify_session(poller, MAMDA_OUJDA, vault_dir=world["vault"], backend=world["backend"]))
    finally:
        poller.close()
    assert stored["cookies"][0]["value"] == MARKER
    for p in world["vault"].iterdir():
        assert MARKER.encode() not in p.read_bytes()
    # nothing sensitive in the database
    tables = [r["name"] for r in world["conn"].execute("SELECT name FROM sqlite_master WHERE type='table'")]
    dump = " ".join(str([tuple(r) for r in world["conn"].execute(f"SELECT * FROM {t}")]) for t in tables)
    assert MARKER not in dump and env["claim_token"] not in dump and world["secret"] not in dump


def test_lost_response_retry_of_complete_is_idempotent(world):
    env, first = full_login(world)
    again = machine(world).post(path(env, "complete"), headers=bearer(world), json=creds(env, storage_state=good_state("other")))
    assert first.status_code == again.status_code == 200
    assert world["conn"].execute("SELECT COUNT(*) FROM portal_sessions").fetchone()[0] == 1


def test_complete_too_large_is_413_and_nothing_is_stored(world):
    click(world)
    env = claim(world).json()
    big = good_state("x" * 600_000)
    response = machine(world).post(path(env, "complete"), headers=bearer(world), json=creds(env, storage_state=big))
    assert response.status_code == 413
    assert world["conn"].execute("SELECT COUNT(*) FROM portal_sessions").fetchone()[0] == 0


@pytest.mark.parametrize("raw", [
    b"{", b"NaN", b'{"claim_token": "mcma_ot_x", "generation": NaN, "storage_state": {}}',
    b'{"claim_token":"a","claim_token":"b","generation":1,"storage_state":{}}',
    b"[" * 4000, b"[]", b"null",
])
def test_complete_malformed_json_fails_closed(world, raw):
    click(world)
    env = claim(world).json()
    response = machine(world).post(path(env, "complete"), headers={**bearer(world), "content-type": "application/json"}, content=raw)
    assert response.status_code == 400
    assert world["conn"].execute("SELECT COUNT(*) FROM portal_sessions").fetchone()[0] == 0


def test_complete_unknown_field_and_non_finite_number_rejected(world):
    click(world)
    env = claim(world).json()
    post = lambda body: machine(world).post(path(env, "complete"), headers=bearer(world), json=body)
    assert post({**creds(env), "storage_state": good_state(), "extra": 1}).status_code == 400
    bad = good_state()
    bad["cookies"][0]["unknown"] = 1
    assert post(creds(env, storage_state=bad)).status_code == 422


def test_sensitive_markers_are_never_logged(world, caplog):
    caplog.set_level(logging.DEBUG)
    click(world)
    env = claim(world).json()
    bad = good_state("LOG-MARKER-SHOULD-NOT-APPEAR")
    bad["cookies"][0]["bogus"] = True
    machine(world).post(path(env, "complete"), headers=bearer(world), json=creds(env, storage_state=bad))
    assert "LOG-MARKER-SHOULD-NOT-APPEAR" not in caplog.text and env["claim_token"] not in caplog.text


def test_account_lease_busy_is_409_and_retryable(world):
    from mcma.persistence.leases import acquire_lease
    click(world)
    env = claim(world).json()
    held = acquire_lease(world["conn"], OUJDA, "poller", ttl_seconds=60)
    first = machine(world).post(path(env, "complete"), headers=bearer(world), json=creds(env, storage_state=good_state()))
    held.release()
    second = machine(world).post(path(env, "complete"), headers=bearer(world), json=creds(env, storage_state=good_state()))
    assert first.status_code == 409 and first.json()["error"] == "ACCOUNT_BUSY"
    assert second.status_code == 200


def test_fail_endpoint_closes_the_request_and_user_sees_the_outcome(world):
    click(world)
    env = claim(world).json()
    response = machine(world).post(path(env, "fail"), headers=bearer(world), json=creds(env, reason_code="LOGIN_WINDOW_CLOSED"))
    assert response.status_code == 200 and response.json()["status"] == "FAILED"
    assert world["employee"].get(f"/accounts/{OUJDA}/login-status").json()["outcome_code"] == "LOGIN_WINDOW_CLOSED"


def test_mamda_remains_out_of_runner_agent_surfaces(world):
    heartbeat = machine(world).post("/runner/heartbeat", headers=bearer(world), json={
        "protocol_version": 1, "app_version": "0.1.0", "sessions": [{"account_id": MAMDA_OUJDA, "state": "READY"}]})
    assert heartbeat.status_code == 400 and heartbeat.json()["error"] == "ACCOUNT_NOT_ALLOWED"
    click(world, MAMDA_OUJDA)
    assert machine(world).post("/runner/jobs/claim", headers=bearer(world), json={"protocol_version": 1, "app_version": "0.1.0"}).status_code == 204
