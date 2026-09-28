"""The runner registry inside the CENTRAL composition: it is wired, it needs
no browser or background thread, it never degrades health, and it cannot
turn Agent creation on."""

import json
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import mcma.notifications.service as service_module
from central_test_support import FakeLauncher, central_settings
from mcma.app.auth.passwords import hash_password
from mcma.app.central_server import create_central_server

REPO = Path(__file__).resolve().parents[2]
OUJDA, NADOR = "acct-mcma-oujda", "acct-mcma-nador"


@pytest.fixture()
def launcher(monkeypatch):
    fake = FakeLauncher()
    monkeypatch.setattr(service_module, "launch_browser", fake)
    return fake


def _server(tmp_path):
    return create_central_server(central_settings(tmp_path), _test_only_portable_mutex=True)


def _client(server):
    return TestClient(server.app, base_url="https://testserver", client=("127.0.0.1", 5000))


def _seed(server):
    conn = server.api_conn
    for uid, name, role in (("boss-id", "boss", "admin"), ("emp-id", "emp", "operator")):
        conn.execute("INSERT INTO users (user_id, username, password_hash, role, active) VALUES (?, ?, ?, ?, 1)",
                     (uid, name, hash_password("pw-for-tests-123"), role))
        for account in (OUJDA, NADOR):
            conn.execute("INSERT INTO user_account_access (user_id, account_id, granted_at) VALUES (?, ?, 'now')", (uid, account))


def _login(client, name):
    r = client.post("/auth/login", json={"username": name, "password": "pw-for-tests-123"})
    assert r.status_code == 200
    return {"X-CSRF-Token": r.json()["csrf_token"]}


def test_central_serves_the_registry_and_a_missing_runner_does_not_degrade_health(tmp_path, launcher):
    server = _server(tmp_path)
    _seed(server)
    with _client(server) as client:
        health, ready = client.get("/health").json(), client.get("/ready")
        assert health["db"] is True and ready.status_code == 200 and ready.json()["ready"] is True
        _login(client, "boss")
        overview = client.get("/admin/runners")
        assert overview.status_code == 200 and overview.json()["runners"] == []
        assert [e["username"] for e in overview.json()["eligible_employees"]] == ["boss", "emp"]
        assert client.get("/health").json()["status"] == "ok"            # still fine with zero runners


def test_registry_operations_launch_no_browser_and_start_no_thread(tmp_path, launcher):
    import threading

    server = _server(tmp_path)
    _seed(server)
    with _client(server) as client:
        launches_before = len(launcher.launches)
        csrf = _login(client, "boss")
        code = client.post("/admin/runner-enrollments", json={"target_user_id": "emp-id"}, headers=csrf).json()["pairing_code"]
        enrolled = TestClient(server.app, base_url="https://testserver").post(
            "/runner/enroll", json={"pairing_code": code, "protocol_version": 1, "app_version": "0.1.0"}).json()
        beat = TestClient(server.app, base_url="https://testserver").post(
            "/runner/heartbeat", headers={"Authorization": f"Bearer {enrolled['runner_secret']}"},
            json={"protocol_version": 1, "app_version": "0.1.0", "sessions": [{"account_id": OUJDA, "state": "READY"}]})
        assert beat.status_code == 200
        assert len(launcher.launches) == launches_before                  # only the notification browser exists
        assert all(b.headless for b in launcher.launches)


def test_agent_creation_stays_503_even_with_an_online_runner(tmp_path, launcher):
    server = _server(tmp_path)
    _seed(server)
    with _client(server) as client:
        csrf = _login(client, "boss")
        code = client.post("/admin/runner-enrollments", json={"target_user_id": "emp-id"}, headers=csrf).json()["pairing_code"]
        secret = TestClient(server.app, base_url="https://testserver").post(
            "/runner/enroll", json={"pairing_code": code, "protocol_version": 1, "app_version": "0.1.0"}).json()["runner_secret"]
        TestClient(server.app, base_url="https://testserver").post(
            "/runner/heartbeat", headers={"Authorization": f"Bearer {secret}"},
            json={"protocol_version": 1, "app_version": "0.1.0", "sessions": [{"account_id": OUJDA, "state": "READY"}]})
        employee = _client(server)
        _login(employee, "emp")
        assert employee.get("/runner-status").json()["status"] == "ONLINE"
        body = {"account_id": OUJDA, "typed_input": {"x": 1}, "idempotency_key": "k1"}
        for path in ("/jobs/dry-runs", "/jobs/some-job/executions"):
            response = client.post(path, json=body, headers=csrf)
            assert response.status_code == 503 and response.json()["error"] == "RUNNER_CONTROL_PLANE_UNAVAILABLE"
        assert server.api_conn.execute("SELECT COUNT(*) AS c FROM automation_jobs").fetchone()["c"] == 0


def test_agent_creation_stays_503_even_though_the_dispatch_endpoints_exist(tmp_path, launcher):
    """Phase 1C-A adds /runner/jobs/claim|renew|release to the SAME
    runner_registry-gated block as enroll/heartbeat -- proving those routes
    now exist and even WORK (a claim returns 204 with no eligible work,
    since no job can exist while Agent creation itself is still refused) is
    not enough: central Agent job CREATION must stay 503/
    RUNNER_CONTROL_PLANE_UNAVAILABLE regardless, exactly like heartbeat
    already does not turn it on."""
    server = _server(tmp_path)
    _seed(server)
    with _client(server) as client:
        csrf = _login(client, "boss")
        code = client.post("/admin/runner-enrollments", json={"target_user_id": "emp-id"}, headers=csrf).json()["pairing_code"]
        secret = TestClient(server.app, base_url="https://testserver").post(
            "/runner/enroll", json={"pairing_code": code, "protocol_version": 1, "app_version": "0.1.0"}).json()["runner_secret"]
        TestClient(server.app, base_url="https://testserver").post(
            "/runner/heartbeat", headers={"Authorization": f"Bearer {secret}"},
            json={"protocol_version": 1, "app_version": "0.1.0", "sessions": [{"account_id": OUJDA, "state": "READY"}]})

        claim = TestClient(server.app, base_url="https://testserver").post(
            "/runner/jobs/claim", headers={"Authorization": f"Bearer {secret}"},
            json={"protocol_version": 1, "app_version": "0.1.0"})
        assert claim.status_code == 204                # the transport works: no eligible work exists

        body = {"account_id": OUJDA, "typed_input": {"x": 1}, "idempotency_key": "k1"}
        for path in ("/jobs/dry-runs", "/jobs/some-job/executions"):
            response = client.post(path, json=body, headers=csrf)
            assert response.status_code == 503 and response.json()["error"] == "RUNNER_CONTROL_PLANE_UNAVAILABLE"
        assert server.api_conn.execute("SELECT COUNT(*) AS c FROM automation_jobs").fetchone()["c"] == 0


def test_the_migration_ran_at_central_startup(tmp_path, launcher):
    server = _server(tmp_path)
    tables = {r["name"] for r in server.api_conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert {"runners", "runner_enrollments", "runner_account_capabilities"} <= tables
    server.close()


def _modules_after_importing(target):
    probe = f"import json, sys\nimport {target}\nprint(json.dumps(sorted(m for m in sys.modules)))"
    result = subprocess.run([sys.executable, "-c", probe], cwd=REPO, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr[-1500:]
    return set(json.loads(result.stdout.strip().splitlines()[-1]))


@pytest.mark.parametrize("target", ["mcma.app.runners.registry", "mcma.app.api.runners"])
def test_the_registry_imports_no_execution_browser_writer_or_portal_login_code(target):
    loaded = _modules_after_importing(target)
    for forbidden in ("mcma.execution.runner", "mcma.execution.browser_handoff", "mcma.portal.writer",
                      "mcma.portal.pilot_contracts", "mcma.app.portal_login", "mcma.portal.browser",
                      "mcma.app.main", "playwright", "mock_server"):
        assert forbidden not in loaded, forbidden


def test_central_startup_import_isolation_still_holds_with_the_registry_wired():
    loaded = _modules_after_importing("mcma.app.central_server")
    for forbidden in ("mcma.app.main", "mcma.execution.runner", "mcma.execution.browser_handoff",
                      "mcma.portal.writer", "mcma.portal.pilot_contracts", "mock_server"):
        assert forbidden not in loaded, forbidden


def test_local_composition_does_not_register_the_registry(tmp_path):
    import mcma.app.main as main_module
    from mcma.core.config import Settings

    settings = Settings(db_path=tmp_path / "l.sqlite3", vault_dir=tmp_path / "v", dev_mode=True,
                        allow_test_plaintext_job_inputs=True, allow_test_only_session_vault=True,
                        mutex_name=f"mcma-local-{tmp_path.name}")
    mutex, api_conn, _, encryptor = main_module.startup(settings, _test_only_portable_mutex=True)
    try:
        paths = {getattr(r, "path", "") for r in main_module.build_app(api_conn, settings, encryptor).routes}
        api_paths = {p for p in paths if p.startswith("/runner") or p.startswith("/admin/runner")}
        assert api_paths == set()                                  # the page shell may exist; the API must not
    finally:
        mutex.release()
