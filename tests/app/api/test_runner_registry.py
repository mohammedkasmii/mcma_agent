"""Workstation-runner registry (Phase 1A): schema, pairing, runner
authentication, heartbeat, authorization, secrecy. Registry only -- no job
claiming, dispatch, browser or portal login exists here."""

import logging
import sqlite3
import threading
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from api_test_support import (  # noqa: F401
    MAMDA_NADOR, MAMDA_OUJDA, NADOR, OUJDA, conn, create_user, csrf_headers, db_path, grant_access, login_client,
)
from mcma.app.api.app import create_api_app
from mcma.app.auth.provider import LocalUserAuthProvider
from mcma.app.auth.sessions import SessionStore
from mcma.app.auth.users import UserInputError
from mcma.app.runners import registry
from mcma.execution.inputs import TestOnlyPlaintextEncryptor
from mcma.persistence import db as db_module
from mcma.persistence.db import open_database

PASSWORD = "correct horse battery"
ALL = [OUJDA, NADOR, MAMDA_OUJDA, MAMDA_NADOR]


def _app(conn, *, registry_enabled=True):
    app = create_api_app(conn, auth_provider=LocalUserAuthProvider(conn), session_store=SessionStore(),
                         encryptor=TestOnlyPlaintextEncryptor(), secure_cookies=True, runner_registry=registry_enabled)
    return app


def _client(app):
    return TestClient(app, base_url="https://testserver", client=("203.0.113.9", 4000))


def _user(conn, name, role, accounts=()):
    uid = create_user(conn, name, PASSWORD, role)
    for account in accounts:
        grant_access(conn, uid, account)
    return uid


@pytest.fixture()
def world(conn):
    boss = _user(conn, "boss", "admin", ALL)
    emp = _user(conn, "emp", "operator", [OUJDA, NADOR, MAMDA_OUJDA])
    app = _app(conn)
    admin = _client(app)
    csrf = login_client(admin, "boss", PASSWORD)
    return {"conn": conn, "app": app, "admin": admin, "csrf": csrf, "boss": boss, "emp": emp}


def _pair(w, target=None, label=None):
    body = {"target_user_id": target or w["emp"]}
    if label is not None:
        body["runner_label"] = label
    return w["admin"].post("/admin/runner-enrollments", json=body, headers=csrf_headers(w["csrf"]))


def _machine(w):
    return _client(w["app"])                   # fresh client: no cookies at all


def _enroll(w, code, **extra):
    body = {"pairing_code": code, "protocol_version": 1, "app_version": "0.1.0", **extra}
    return _machine(w).post("/runner/enroll", json=body)


def _enrolled(w, **kwargs):
    code = _pair(w, **kwargs).json()["pairing_code"]
    response = _enroll(w, code)
    assert response.status_code == 201, response.text
    return response.json()


def _hb(w, secret, sessions=None, **overrides):
    body = {"protocol_version": 1, "app_version": "0.1.0",
            "sessions": sessions if sessions is not None else [{"account_id": OUJDA, "state": "READY"}], **overrides}
    headers = {"Authorization": f"Bearer {secret}"} if secret is not None else {}
    return _machine(w).post("/runner/heartbeat", json=body, headers=headers)


def _dump_db(conn):
    tables = [r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    return " ".join(str([tuple(r) for r in conn.execute(f"SELECT * FROM {t}").fetchall()]) for t in tables)


# ------------------------------------ schema ---------------------------------------- #


def test_migration_creates_the_registry_tables_with_foreign_key_integrity(conn):
    names = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert {"runner_enrollments", "runners", "runner_account_capabilities"} <= names
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert conn.execute("SELECT version FROM schema_migrations WHERE version LIKE '0005%'").fetchone()


def test_upgrade_from_the_previous_schema_preserves_data_and_adds_the_registry(tmp_path, monkeypatch):
    real = db_module._migration_files
    monkeypatch.setattr(db_module, "_migration_files", lambda: [p for p in real() if not p.stem.startswith("0005")])
    old = open_database(tmp_path / "up.sqlite3")
    old.execute("INSERT INTO users (user_id, username, password_hash, role, active) VALUES ('u1', 'keep', 'x', 'operator', 1)")
    assert "runners" not in {r["name"] for r in old.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    old.close()
    monkeypatch.undo()
    upgraded = open_database(tmp_path / "up.sqlite3")
    try:
        assert upgraded.execute("SELECT username FROM users").fetchone()["username"] == "keep"
        assert upgraded.execute("SELECT COUNT(*) AS c FROM runners").fetchone()["c"] == 0
        assert upgraded.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        upgraded.close()


def _insert_runner(conn, user_id, *, status="ACTIVE", n=[0]):
    n[0] += 1
    revoked = "'2026-01-01T00:00:00+00:00'" if status == "REVOKED" else "NULL"
    conn.execute(
        "INSERT INTO runner_enrollments (enrollment_id, code_digest, target_user_id, created_by_user_id, created_at, expires_at) "
        "VALUES (?, ?, ?, ?, 'now', 'later')", (f"e{n[0]}", f"{n[0]:064d}", user_id, user_id))
    conn.execute(
        f"INSERT INTO runners (runner_id, user_id, credential_digest, runner_label, status, enrollment_id, created_at, revoked_at) "
        f"VALUES (?, ?, ?, 'L', ?, ?, 'now', {revoked})", (f"r{n[0]}", user_id, f"{n[0] + 500:064d}", status, f"e{n[0]}"))
    return f"r{n[0]}"


def test_the_database_allows_only_one_active_runner_per_user_but_keeps_history(conn):
    uid = _user(conn, "emp", "operator", [OUJDA])
    _insert_runner(conn, uid, status="REVOKED")
    _insert_runner(conn, uid, status="REVOKED")
    _insert_runner(conn, uid)                                              # one active next to history: fine
    with pytest.raises(sqlite3.IntegrityError):
        _insert_runner(conn, uid)
    assert conn.execute("SELECT COUNT(*) AS c FROM runners WHERE user_id = ?", (uid,)).fetchone()["c"] == 3


def test_capability_rows_reject_mamda_unknown_accounts_and_bad_states_in_the_database(conn):
    uid = _user(conn, "emp", "operator", [OUJDA])
    rid = _insert_runner(conn, uid)
    good = "INSERT INTO runner_account_capabilities (runner_id, account_id, session_state, updated_at) VALUES (?, ?, ?, 'now')"
    conn.execute(good, (rid, OUJDA, "READY"))
    for account in (MAMDA_OUJDA, MAMDA_NADOR, "acct-nope"):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(good, (rid, account, "READY"))
    for state in ("ONLINE", "ready", "", "OK"):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(good, (rid, NADOR, state))


def test_table_checks_reject_malformed_digests_and_inconsistent_revocation(conn):
    uid = _user(conn, "emp", "operator", [OUJDA])
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO runner_enrollments (enrollment_id, code_digest, target_user_id, created_by_user_id, created_at, expires_at) "
                     "VALUES ('e', 'short', ?, ?, 'a', 'b')", (uid, uid))
    _insert_runner(conn, uid)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE runners SET status = 'REVOKED' WHERE user_id = ?", (uid,))     # revoked_at missing


def test_the_schema_stores_no_secret_shaped_or_status_columns_beyond_the_contract(conn):
    cols = {t: [r["name"] for r in conn.execute(f"PRAGMA table_info({t})").fetchall()]
            for t in ("runners", "runner_enrollments", "runner_account_capabilities")}
    flat = " ".join(" ".join(c) for c in cols.values())
    for forbidden in ("password", "cookie", "storage", "otp", "hostname", "windows", "raw", "secret", "token", "online", "status_text"):
        assert forbidden not in flat.replace("credential_digest", ""), forbidden
    assert "credential_digest" in cols["runners"] and "code_digest" in cols["runner_enrollments"]


# --------------------------------- pairing ------------------------------------------ #


def test_admin_creates_a_pairing_code_shown_once_with_safe_metadata(world):
    response = _pair(world, label="Poste Sara")
    assert response.status_code == 201 and response.headers["cache-control"] == "no-store"
    body = response.json()
    assert set(body) == {"enrollment", "pairing_code"} and body["pairing_code"].startswith("mcma_pc_")
    assert len(body["pairing_code"]) >= 8 + 43                               # 256 bits, URL-safe
    assert body["enrollment"]["target_username"] == "emp" and body["enrollment"]["runner_label"] == "Poste Sara"
    listing = world["admin"].get("/admin/runners")
    assert body["pairing_code"] not in listing.text and "pairing_code" not in listing.text
    pending = listing.json()["pending_enrollments"]
    assert [p["target_username"] for p in pending] == ["emp"] and set(pending[0]) == {
        "enrollment_id", "target_user_id", "target_username", "runner_label", "expires_at"}


def test_default_expiry_is_ten_minutes_from_the_server_clock(world):
    body = _pair(world).json()
    created = world["conn"].execute("SELECT created_at, expires_at FROM runner_enrollments").fetchone()
    delta = datetime.fromisoformat(created["expires_at"]) - datetime.fromisoformat(created["created_at"])
    assert delta == timedelta(seconds=600) == timedelta(seconds=registry.ENROLLMENT_TTL_SECONDS)
    assert body["enrollment"]["expires_at"] == created["expires_at"]


def test_enrollment_returns_the_runner_credential_once_and_only_allowed_accounts(world):
    enrolled = _enrolled(world)
    assert set(enrolled) == {"runner_id", "runner_secret", "runner_label", "allowed_account_ids",
                             "heartbeat_interval_seconds", "offline_after_seconds", "server_time"}
    assert enrolled["runner_secret"].startswith("mcma_rs_") and len(enrolled["runner_secret"]) >= 8 + 43
    assert enrolled["allowed_account_ids"] == sorted([OUJDA, NADOR])            # MCMA only; MAMDA_OUJDA excluded
    assert (enrolled["heartbeat_interval_seconds"], enrolled["offline_after_seconds"]) == (10, 30)
    listing = world["admin"].get("/admin/runners").text
    assert enrolled["runner_secret"] not in listing and "credential" not in listing and "digest" not in listing


def test_a_pairing_code_is_single_use(world):
    code = _pair(world).json()["pairing_code"]
    assert _enroll(world, code).status_code == 201
    again = _enroll(world, code)
    assert again.status_code == 400 and again.json()["error"] == "PAIRING_CODE_INVALID"
    assert world["conn"].execute("SELECT COUNT(*) AS c FROM runners").fetchone()["c"] == 1


def test_expired_consumed_revoked_and_unknown_codes_are_refused_identically(world):
    conn = world["conn"]
    expired = _pair(world).json()["pairing_code"]
    conn.execute("UPDATE runner_enrollments SET expires_at = '2000-01-01T00:00:00+00:00'")
    consumed_code = None
    boss_two = _user(conn, "emp2", "operator", [NADOR])
    consumed_code = _pair(world, target=boss_two).json()["pairing_code"]
    assert _enroll(world, consumed_code).status_code == 201
    third = _user(conn, "emp3", "operator", [OUJDA])
    revoked_code = _pair(world, target=third).json()["pairing_code"]
    conn.execute("UPDATE runner_enrollments SET revoked_at = '2026-01-01T00:00:00+00:00' WHERE target_user_id = ?", (third,))
    answers = [_enroll(world, c) for c in (expired, consumed_code, revoked_code, "mcma_pc_" + "x" * 43, "short", "")]
    assert {(a.status_code, a.json()["error"], a.json()["message"]) for a in answers} == {
        (400, "PAIRING_CODE_INVALID", "Code d'association invalide, expiré ou déjà utilisé.")}


def test_a_new_code_revokes_the_older_unused_one(world):
    first = _pair(world).json()["pairing_code"]
    second = _pair(world).json()["pairing_code"]
    assert _enroll(world, first).status_code == 400
    assert _enroll(world, second).status_code == 201


@pytest.mark.parametrize("kind", ["viewer", "inactive", "no_mcma_access", "mamda_only", "unknown"])
def test_ineligible_targets_are_refused(world, kind):
    conn = world["conn"]
    if kind == "viewer":
        target = _user(conn, "vw", "viewer", [OUJDA])
    elif kind == "inactive":
        target = _user(conn, "off", "operator", [OUJDA])
        conn.execute("UPDATE users SET active = 0 WHERE user_id = ?", (target,))
    elif kind == "no_mcma_access":
        target = _user(conn, "none", "operator", [])
    elif kind == "mamda_only":
        target = _user(conn, "md", "operator", [MAMDA_OUJDA, MAMDA_NADOR])
    else:
        target = "no-such-user"
    response = _pair(world, target=target)
    assert response.status_code in (404, 409)
    assert response.json()["error"] in ("TARGET_NOT_ELIGIBLE", "USER_NOT_FOUND")
    assert conn.execute("SELECT COUNT(*) AS c FROM runner_enrollments").fetchone()["c"] == 0


def test_an_active_runner_blocks_a_new_enrollment_until_revoked(world):
    enrolled = _enrolled(world)
    blocked = _pair(world)
    assert blocked.status_code == 409 and blocked.json()["error"] == "RUNNER_ALREADY_ACTIVE"
    assert world["admin"].post(f"/admin/runners/{enrolled['runner_id']}/revoke", headers=csrf_headers(world["csrf"])).status_code == 200
    assert _pair(world).status_code == 201


def test_a_code_cannot_enroll_when_the_target_became_ineligible(world):
    code = _pair(world).json()["pairing_code"]
    world["conn"].execute("UPDATE users SET active = 0 WHERE user_id = ?", (world["emp"],))
    assert _enroll(world, code).status_code == 400


def test_concurrent_enrollments_with_one_code_yield_exactly_one_runner(world):
    conn = world["conn"]
    code = _pair(world).json()["pairing_code"]
    results, barrier = [], threading.Barrier(8)

    def attempt():
        barrier.wait()
        try:
            registry.enroll(conn, pairing_code=code, protocol_version=1, app_version="0.1.0")
            results.append("ok")
        except UserInputError as exc:
            results.append(exc.code)

    threads = [threading.Thread(target=attempt) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count("ok") == 1 and results.count("PAIRING_CODE_INVALID") == 7
    assert conn.execute("SELECT COUNT(*) AS c FROM runners").fetchone()["c"] == 1


def test_a_failure_during_enrollment_rolls_back_and_leaves_the_code_usable(world, monkeypatch):
    conn = world["conn"]
    code = _pair(world).json()["pairing_code"]
    real = registry._audit
    monkeypatch.setattr(registry, "_audit", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("audit down")))
    with pytest.raises(RuntimeError):
        registry.enroll(conn, pairing_code=code, protocol_version=1, app_version="0.1.0")
    assert conn.execute("SELECT COUNT(*) AS c FROM runners").fetchone()["c"] == 0
    assert conn.execute("SELECT consumed_at FROM runner_enrollments").fetchone()["consumed_at"] is None
    monkeypatch.setattr(registry, "_audit", real)
    assert _enroll(world, code).status_code == 201


@pytest.mark.parametrize("body", [
    {}, {"target_user_id": 5}, {"target_user_id": "x", "extra": 1}, {"target_user_id": "u", "runner_label": "bad;label"},
    {"target_user_id": "u", "runner_label": "x" * 41}, {"target_user_id": "u", "runner_label": ""},
    {"target_user_id": "u", "runner_label": {"a": 1}},
])
def test_enrollment_creation_bodies_are_validated_strictly_without_echo(world, body):
    response = world["admin"].post("/admin/runner-enrollments", json=body, headers=csrf_headers(world["csrf"]))
    assert response.status_code in (400, 404)
    assert "bad;label" not in response.text and "extra" not in response.text
    assert world["conn"].execute("SELECT COUNT(*) AS c FROM runner_enrollments").fetchone()["c"] == 0


# --------------------------- runner authentication ---------------------------------- #


def test_heartbeat_authenticates_with_a_bearer_credential_only(world):
    enrolled = _enrolled(world)
    secret = enrolled["runner_secret"]
    assert _hb(world, secret).status_code == 200
    client = _machine(world)
    body = {"protocol_version": 1, "app_version": "0.1.0", "sessions": []}
    for attempt in (
        client.post("/runner/heartbeat", json=body),                                                     # missing
        client.post("/runner/heartbeat", json=body, headers={"Authorization": "Basic " + secret}),        # wrong scheme
        client.post("/runner/heartbeat", json=body, headers={"Authorization": "Bearer"}),
        client.post("/runner/heartbeat", json=body, headers={"Authorization": "Bearer mcma_rs_" + "A" * 43}),   # unknown
        client.post("/runner/heartbeat", json=body, headers={"Authorization": "Bearer " + "x" * 500}),
        client.post(f"/runner/heartbeat?token={secret}", json=body),                                      # never a query parameter
        client.post("/runner/heartbeat", json={**body, "runner_secret": secret, "token": secret}),        # never the body
    ):
        assert attempt.status_code in (400, 401)
        if attempt.status_code == 401:
            assert attempt.json()["error"] == "RUNNER_UNAUTHENTICATED"
    client.cookies.set("runner_secret", secret)
    assert client.post("/runner/heartbeat", json=body).status_code == 401                                  # never a cookie


def test_all_credential_failures_are_one_generic_401_that_never_names_a_runner(world):
    enrolled = _enrolled(world)
    revoked_secret = enrolled["runner_secret"]
    world["admin"].post(f"/admin/runners/{enrolled['runner_id']}/revoke", headers=csrf_headers(world["csrf"]))
    responses = [_hb(world, s) for s in (None, "garbage", revoked_secret, "mcma_rs_" + "B" * 43)]
    shapes = {(r.status_code, r.json()["error"], r.json()["message"]) for r in responses}
    assert shapes == {(401, "RUNNER_UNAUTHENTICATED", "authentification du poste refusée")}
    assert enrolled["runner_id"] not in " ".join(r.text for r in responses)


def test_revocation_takes_effect_immediately(world):
    enrolled = _enrolled(world)
    assert _hb(world, enrolled["runner_secret"]).status_code == 200
    revoked = world["admin"].post(f"/admin/runners/{enrolled['runner_id']}/revoke", headers=csrf_headers(world["csrf"]))
    assert revoked.status_code == 200 and revoked.json()["runner"]["status"] == "REVOKED"
    assert _hb(world, enrolled["runner_secret"]).status_code == 401
    again = world["admin"].post(f"/admin/runners/{enrolled['runner_id']}/revoke", headers=csrf_headers(world["csrf"]))
    assert again.status_code == 200 and again.json()["already_revoked"] is True
    audit = world["conn"].execute("SELECT COUNT(*) AS c FROM audit_events WHERE action = 'runner.revoked'").fetchone()["c"]
    assert audit == 1                                                       # idempotent, audited once
    row = world["conn"].execute("SELECT status, revoked_at FROM runners").fetchone()
    assert row["status"] == "REVOKED" and row["revoked_at"]                # retained, never deleted


def test_revoking_an_unknown_runner_is_a_404(world):
    r = world["admin"].post("/admin/runners/nope/revoke", headers=csrf_headers(world["csrf"]))
    assert r.status_code == 404 and r.json()["error"] == "RUNNER_NOT_FOUND"


def test_employee_sessions_cannot_authenticate_runner_endpoints_and_vice_versa(world):
    enrolled = _enrolled(world)
    secret = enrolled["runner_secret"]
    # An employee/admin session cookie is not a runner credential.
    body = {"protocol_version": 1, "app_version": "0.1.0", "sessions": []}
    assert world["admin"].post("/runner/heartbeat", json=body).status_code == 401
    # A runner credential is not an employee session (as bearer or as cookie).
    machine = _machine(world)
    bearer = {"Authorization": f"Bearer {secret}"}
    for path in ("/auth/me", "/runner-status", "/admin/runners", "/admin/users", "/accounts", "/notifications"):
        assert machine.get(path, headers=bearer).status_code == 401, path
    machine.cookies.set("mcma_session", secret)
    assert machine.get("/auth/me").status_code == 401
    assert machine.post("/admin/runner-enrollments", json={"target_user_id": world["emp"]}, headers=bearer).status_code in (401, 403)


def test_machine_endpoints_need_no_csrf_and_admin_mutations_do(world):
    code = _pair(world).json()["pairing_code"]
    assert _enroll(world, code).status_code == 201                          # no CSRF cookie or header anywhere
    assert world["admin"].post("/admin/runner-enrollments", json={"target_user_id": world["emp"]}).status_code == 403
    assert world["admin"].post("/admin/runners/x/revoke").status_code == 403
    assert world["admin"].post("/admin/runner-enrollments", json={"target_user_id": world["emp"]},
                               headers={"X-CSRF-Token": "wrong"}).status_code == 403


# ------------------------------------ heartbeat ------------------------------------- #


def test_heartbeat_records_server_time_and_readiness_and_ignores_client_time(world):
    enrolled = _enrolled(world)
    before = datetime.now(timezone.utc)
    response = _hb(world, enrolled["runner_secret"],
                   [{"account_id": OUJDA, "state": "READY"}, {"account_id": NADOR, "state": "LOGIN_REQUIRED"}])
    after = datetime.now(timezone.utc)
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    body = response.json()
    assert set(body) == {"status", "server_time", "heartbeat_interval_seconds", "offline_after_seconds", "allowed_account_ids"}
    assert before <= datetime.fromisoformat(body["server_time"]) <= after
    seen = world["conn"].execute("SELECT last_seen_at FROM runners").fetchone()["last_seen_at"]
    assert seen == body["server_time"]
    admin_view = world["admin"].get("/admin/runners").json()["runners"][0]
    assert admin_view["status"] == "ONLINE"
    assert admin_view["sessions"] == [{"account_id": OUJDA, "state": "READY"}, {"account_id": NADOR, "state": "LOGIN_REQUIRED"}]


@pytest.mark.parametrize("extra", [{"last_seen_at": "1999-01-01"}, {"runner_id": "forged"}, {"assigned_user_id": "x"},
                                   {"user_id": "x"}, {"status": "ONLINE"}])
def test_the_client_cannot_choose_identity_time_or_status(world, extra):
    enrolled = _enrolled(world)
    r = _hb(world, enrolled["runner_secret"], **extra)
    assert r.status_code == 400 and r.json()["error"] == "BAD_REQUEST"
    assert world["conn"].execute("SELECT last_seen_at FROM runners").fetchone()["last_seen_at"] is None


def test_online_offline_is_derived_from_server_time_with_centralized_constants(world):
    assert (registry.HEARTBEAT_INTERVAL_SECONDS, registry.OFFLINE_AFTER_SECONDS) == (10, 30)
    enrolled = _enrolled(world)
    conn = world["conn"]
    assert world["admin"].get("/admin/runners").json()["runners"][0]["status"] == "OFFLINE"    # never seen
    row = lambda: conn.execute("SELECT * FROM runners").fetchone()
    now = datetime.now(timezone.utc)
    for age, expected in ((0, "ONLINE"), (10, "ONLINE"), (29, "ONLINE"), (31, "OFFLINE"), (3600, "OFFLINE")):
        conn.execute("UPDATE runners SET last_seen_at = ?", ((now - timedelta(seconds=age)).isoformat(),))
        assert registry.runner_view(conn, row(), now)["status"] == expected, age
        assert world["admin"].get("/admin/runners").json()["runners"][0]["status"] in ("ONLINE", "OFFLINE")
    assert "online" not in [c["name"] for c in conn.execute("PRAGMA table_info(runners)").fetchall()]
    assert enrolled["runner_id"]


@pytest.mark.parametrize("sessions", [
    [{"account_id": MAMDA_OUJDA, "state": "READY"}], [{"account_id": MAMDA_NADOR, "state": "READY"}],
    [{"account_id": "acct-nope", "state": "READY"}], [{"account_id": OUJDA, "state": "ONLINE"}],
    [{"account_id": OUJDA}], [{"account_id": OUJDA, "state": "READY", "note": "hi"}],
    [{"account_id": OUJDA, "state": "READY"}] * 2, "READY", None, [1], [{"account_id": 5, "state": "READY"}],
    [{"account_id": OUJDA, "state": "READY"}, {"account_id": NADOR, "state": "READY"}, {"account_id": OUJDA, "state": "ERROR"}],
])
def test_bad_or_disallowed_session_payloads_are_rejected(world, sessions):
    enrolled = _enrolled(world)
    r = _machine(world).post("/runner/heartbeat", json={"protocol_version": 1, "app_version": "1", "sessions": sessions},
                             headers={"Authorization": f"Bearer {enrolled['runner_secret']}"})
    assert r.status_code == 400 and r.json()["error"] in ("BAD_REQUEST", "ACCOUNT_NOT_ALLOWED")
    assert world["conn"].execute("SELECT COUNT(*) AS c FROM runner_account_capabilities").fetchone()["c"] == 0


def test_an_account_the_employee_cannot_access_is_rejected(world):
    only_oujda = _user(world["conn"], "solo", "operator", [OUJDA])
    enrolled = _enrolled(world, target=only_oujda)
    ok = _hb(world, enrolled["runner_secret"], [{"account_id": OUJDA, "state": "READY"}])
    denied = _hb(world, enrolled["runner_secret"], [{"account_id": NADOR, "state": "READY"}])
    assert ok.status_code == 200 and denied.status_code == 400 and denied.json()["error"] == "ACCOUNT_NOT_ALLOWED"
    assert ok.json()["allowed_account_ids"] == [OUJDA]


@pytest.mark.parametrize("override", [{"protocol_version": 2}, {"protocol_version": "1"}, {"protocol_version": True},
                                      {"app_version": ""}, {"app_version": "x" * 33}, {"app_version": "bad version!"},
                                      {"app_version": 5}])
def test_versions_are_validated(world, override):
    enrolled = _enrolled(world)
    r = _hb(world, enrolled["runner_secret"], **override)
    assert r.status_code == 400


def test_oversized_and_malformed_bodies_are_rejected(world):
    enrolled = _enrolled(world)
    machine = _machine(world)
    headers = {"Authorization": f"Bearer {enrolled['runner_secret']}"}
    huge = {"protocol_version": 1, "app_version": "1", "sessions": [], "pad": "x" * 10_000}
    assert machine.post("/runner/heartbeat", json=huge, headers=headers).status_code == 413
    assert machine.post("/runner/heartbeat", content=b"{not json", headers={**headers, "Content-Type": "application/json"}).status_code == 400
    assert machine.post("/runner/heartbeat", json=[1, 2], headers=headers).status_code == 400
    assert machine.post("/runner/enroll", json={"pairing_code": "x" * 10_000, "protocol_version": 1, "app_version": "1"}).status_code == 413


@pytest.mark.parametrize("change", ["deactivate", "demote_to_viewer", "remove_mcma_access"])
def test_a_runner_fails_closed_when_its_employee_loses_eligibility(world, change):
    enrolled = _enrolled(world)
    conn = world["conn"]
    assert _hb(world, enrolled["runner_secret"]).status_code == 200
    if change == "deactivate":
        conn.execute("UPDATE users SET active = 0 WHERE user_id = ?", (world["emp"],))
    elif change == "demote_to_viewer":
        conn.execute("UPDATE users SET role = 'viewer' WHERE user_id = ?", (world["emp"],))
    else:
        conn.execute("DELETE FROM user_account_access WHERE user_id = ? AND account_id IN (?, ?)", (world["emp"], OUJDA, NADOR))
    assert _hb(world, enrolled["runner_secret"]).status_code == 401
    row = conn.execute("SELECT status, revoked_at FROM runners").fetchone()
    assert row["status"] == "REVOKED" and row["revoked_at"]                    # durable, not just refused
    assert conn.execute("SELECT COUNT(*) AS c FROM audit_events WHERE action = 'runner.auto_revoked'").fetchone()["c"] == 1
    conn.execute("UPDATE users SET active = 1, role = 'operator' WHERE user_id = ?", (world["emp"],))
    assert _hb(world, enrolled["runner_secret"]).status_code == 401           # restoring the employee does not revive it


def test_concurrent_heartbeats_are_safe(world):
    enrolled = _enrolled(world)
    conn = world["conn"]
    principal = registry.authenticate_runner(conn, enrolled["runner_secret"])
    errors, barrier = [], threading.Barrier(10)

    def beat(i):
        try:
            barrier.wait()
            for n in range(40):
                state = ("READY", "ERROR", "LOGIN_REQUIRED")[(i + n) % 3]
                registry.heartbeat(conn, principal, protocol_version=1, app_version="0.1.0",
                                   sessions=[{"account_id": OUJDA, "state": state}, {"account_id": NADOR, "state": "READY"}])
        except BaseException as exc:                # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=beat, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert conn.execute("SELECT COUNT(*) AS c FROM runner_account_capabilities").fetchone()["c"] == 2


# ----------------------------- authorization and isolation ----------------------------- #


@pytest.mark.parametrize("role", ["operator", "viewer"])
def test_operators_and_viewers_cannot_manage_runners(world, role):
    conn = world["conn"]
    _user(conn, "worker", role, [OUJDA])
    client = _client(world["app"])
    csrf = login_client(client, "worker", PASSWORD)
    enrolled = _enrolled(world)
    calls = [
        client.get("/admin/runners"),
        client.post("/admin/runner-enrollments", json={"target_user_id": world["emp"]}, headers=csrf_headers(csrf)),
        client.post(f"/admin/runners/{enrolled['runner_id']}/revoke", headers=csrf_headers(csrf)),
    ]
    assert [c.status_code for c in calls] == [403, 403, 403]
    assert conn.execute("SELECT status FROM runners").fetchone()["status"] == "ACTIVE"


def test_unauthenticated_requests_to_admin_and_status_endpoints_are_401(world):
    anon = _machine(world)
    assert anon.get("/admin/runners").status_code == 401
    assert anon.get("/runner-status").status_code == 401
    assert anon.post("/admin/runner-enrollments", json={}).status_code in (401, 403)


def test_runners_manage_is_admin_only_in_the_role_map():
    from mcma.app.auth.permissions import permissions_for_role
    from mcma.domain.enums import Permission

    assert Permission.RUNNERS_MANAGE.value == "runners:manage"
    assert Permission.RUNNERS_MANAGE in permissions_for_role("admin")
    assert Permission.RUNNERS_MANAGE not in permissions_for_role("operator")
    assert Permission.RUNNERS_MANAGE not in permissions_for_role("viewer")


def test_employees_see_only_their_own_runner_status(world):
    conn = world["conn"]
    other = _user(conn, "other", "operator", [NADOR])
    mine = _enrolled(world)
    theirs = _enrolled(world, target=other)
    _hb(world, mine["runner_secret"], [{"account_id": OUJDA, "state": "READY"}])
    emp = _client(world["app"])
    login_client(emp, "emp", PASSWORD)
    status = emp.get("/runner-status")
    assert status.status_code == 200 and status.headers["cache-control"] == "no-store"
    body = status.json()
    assert set(body) == {"status", "runner_label", "last_seen_at", "protocol_version", "sessions"}
    assert body["status"] == "ONLINE" and {"account_id": OUJDA, "state": "READY"} in body["sessions"]
    assert mine["runner_id"] not in status.text and theirs["runner_id"] not in status.text and "other" not in status.text
    other_client = _client(world["app"])
    login_client(other_client, "other", PASSWORD)
    assert other_client.get("/runner-status").json()["status"] == "OFFLINE"          # own runner, never seen


def test_runner_status_covers_unpaired_offline_online_and_revoked(world):
    viewer = _user(world["conn"], "vw", "viewer", [OUJDA])
    client = _client(world["app"])
    login_client(client, "vw", PASSWORD)
    assert client.get("/runner-status").json() == {"status": "UNPAIRED", "runner_label": None, "last_seen_at": None,
                                                    "protocol_version": None, "sessions": []}
    emp = _client(world["app"])
    login_client(emp, "emp", PASSWORD)
    assert emp.get("/runner-status").json()["status"] == "UNPAIRED"
    enrolled = _enrolled(world)
    assert emp.get("/runner-status").json()["status"] == "OFFLINE"
    _hb(world, enrolled["runner_secret"])
    assert emp.get("/runner-status").json()["status"] == "ONLINE"
    world["admin"].post(f"/admin/runners/{enrolled['runner_id']}/revoke", headers=csrf_headers(world["csrf"]))
    revoked = emp.get("/runner-status").json()
    assert revoked["status"] == "REVOKED" and revoked["sessions"] == [] and viewer


def test_admins_see_their_own_runner_through_runner_status_but_list_everyone_only_via_admin(world):
    boss_runner = _enrolled(world, target=world["boss"])
    _enrolled(world)
    own = world["admin"].get("/runner-status").json()
    assert own["status"] in ("OFFLINE", "ONLINE") and boss_runner["runner_id"] not in str(own)
    assert len(world["admin"].get("/admin/runners").json()["runners"]) == 2


def test_eligible_employees_exclude_ineligible_and_already_paired_users(world):
    conn = world["conn"]
    _user(conn, "vw", "viewer", [OUJDA])
    _user(conn, "md", "operator", [MAMDA_OUJDA])
    listing = lambda: [e["username"] for e in world["admin"].get("/admin/runners").json()["eligible_employees"]]
    assert listing() == ["boss", "emp"]
    _enrolled(world)
    assert listing() == ["boss"]


# --------------------------------- secrecy and audit ----------------------------------- #


def test_raw_codes_and_secrets_are_absent_from_storage_audit_logs_and_errors(world, caplog):
    caplog.set_level(logging.DEBUG)
    code = _pair(world).json()["pairing_code"]
    enroll_response = _enroll(world, code)
    secret = enroll_response.json()["runner_secret"]
    outputs = [enroll_response.text]
    outputs.append(_enroll(world, code).text)                                       # refused reuse
    outputs.append(_hb(world, secret).text)
    outputs.append(_hb(world, secret + "x").text)                                   # wrong credential
    outputs.append(_hb(world, secret, [{"account_id": MAMDA_OUJDA, "state": "READY"}]).text)
    outputs.append(world["admin"].get("/admin/runners").text)
    outputs.append(_machine(world).post("/runner/enroll", json={"pairing_code": code, "junk": secret}).text)
    conn = world["conn"]
    dump = _dump_db(conn)
    audit = " ".join(str(tuple(r)) for r in conn.execute("SELECT * FROM audit_events").fetchall())
    for raw in (code, secret, code.removeprefix("mcma_pc_"), secret.removeprefix("mcma_rs_")):
        assert raw not in dump and raw not in audit and raw not in caplog.text
    for text in outputs[1:]:
        assert secret not in text and code not in text
    assert registry.digest_secret(code) in dump and registry.digest_secret(secret) in dump     # only digests are stored
    actions = [r["action"] for r in conn.execute("SELECT action FROM audit_events WHERE action LIKE 'runner.%'").fetchall()]
    assert actions == ["runner.enrollment_created", "runner.enrolled"]


def test_the_credential_digest_is_the_only_stored_form_and_comparisons_are_constant_time():
    import inspect

    source = inspect.getsource(registry)
    assert "hmac.compare_digest" in source and "sha256" in source
    assert registry.digest_secret("a") == registry.digest_secret("a") != registry.digest_secret("b")


def test_error_responses_never_contain_exception_text(world, monkeypatch):
    enrolled = _enrolled(world)
    monkeypatch.setattr(registry, "_audit", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("SECRET-INTERNAL-DETAIL")))
    client = TestClient(world["app"], base_url="https://testserver", raise_server_exceptions=False)
    response = client.post(f"/admin/runners/{enrolled['runner_id']}/revoke")
    assert "SECRET-INTERNAL-DETAIL" not in response.text and enrolled["runner_secret"] not in response.text


def test_the_admin_api_derives_the_actor_from_the_session(world):
    _pair(world)
    row = world["conn"].execute("SELECT created_by_user_id FROM runner_enrollments").fetchone()
    assert row["created_by_user_id"] == world["boss"]
    forged = world["admin"].post("/admin/runner-enrollments", headers=csrf_headers(world["csrf"]),
                                 json={"target_user_id": world["emp"], "created_by_user_id": "forged"})
    assert forged.status_code == 400


def test_all_timestamps_are_server_generated_utc(world):
    enrolled = _enrolled(world)
    _hb(world, enrolled["runner_secret"])
    conn = world["conn"]
    for table, column in (("runner_enrollments", "created_at"), ("runner_enrollments", "expires_at"),
                          ("runner_enrollments", "consumed_at"), ("runners", "created_at"), ("runners", "last_seen_at"),
                          ("runner_account_capabilities", "updated_at")):
        for row in conn.execute(f"SELECT {column} AS v FROM {table} WHERE {column} IS NOT NULL").fetchall():
            assert datetime.fromisoformat(row["v"]).utcoffset() == timedelta(0), (table, column)


def test_local_mode_does_not_register_the_registry_routes(conn):
    app = _app(conn, registry_enabled=False)
    paths = {getattr(r, "path", "") for r in app.routes}
    assert not any(p.startswith("/runner") or "runner" in p for p in paths)
    _user(conn, "boss", "admin", ALL)
    client = _client(app)
    login_client(client, "boss", PASSWORD)
    assert client.get("/admin/runners").status_code == 404
