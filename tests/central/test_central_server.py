"""The central server composition root, and regression protection for the
local Windows composition that shares the notification service with it."""

import asyncio
import inspect

import pytest
from fastapi.testclient import TestClient

import mcma.app.central_server as central_module
import mcma.app.composition as composition_module
import mcma.app.main as main_module
import mcma.execution.runner as runner_module
import mcma.notifications.service as service_module
from central_test_support import FakeLauncher, central_settings
from mcma.app.auth.passwords import hash_password
from mcma.app.central_server import create_central_server
from mcma.app.server_status import is_ready, overall_status
from mcma.core.central_config import CentralConfigurationError
from mcma.core.config import Settings
from mcma.core.mutex import MutexAcquisitionError
from mcma.notifications.service import NotificationServiceState

OUJDA = "acct-mcma-oujda"


@pytest.fixture()
def forbid_job_processing(monkeypatch):
    """Any call to either job-processing function fails the test loudly,
    wherever it is reached from."""
    calls = []

    async def forbidden(*args, **kwargs):
        calls.append("called")
        raise AssertionError("the central server must never process jobs")

    for module in (runner_module, main_module):
        monkeypatch.setattr(module, "process_queued_dry_run_jobs", forbidden)
        monkeypatch.setattr(module, "process_queued_planned_execute_jobs", forbidden)
    return calls


@pytest.fixture()
def launcher(monkeypatch):
    fake = FakeLauncher()
    # The service resolves launch_browser at call time; the main module's
    # own reference is also replaced so a headful launch there is caught.
    monkeypatch.setattr(service_module, "launch_browser", fake)
    monkeypatch.setattr(main_module, "launch_browser", fake)
    return fake


def _server(tmp_path, **overrides):
    return create_central_server(central_settings(tmp_path, **overrides), _test_only_portable_mutex=True)


def _client(server):
    return TestClient(server.app, base_url="https://testserver", client=("127.0.0.1", 5000))


# ----------------------------- fail-closed start ------------------------ #


@pytest.mark.parametrize(
    "override",
    [
        {"local_single_user_mode": True},
        {"allow_test_plaintext_job_inputs": True},
        {"allow_test_only_session_vault": True},
        {"dev_mode": True},
        {"allowed_host": "127.0.0.1:8080"},
        {"session_vault_key_path": None},
        {"api_host": "0.0.0.0"},
    ],
)
def test_unsafe_settings_stop_startup_before_anything_opens(tmp_path, override):
    with pytest.raises(CentralConfigurationError):
        _server(tmp_path, **override)
    assert not (tmp_path / "data" / "mcma.sqlite3").exists()


def test_missing_data_directory_is_refused_not_created(tmp_path):
    settings = central_settings(tmp_path, db_path=tmp_path / "nope" / "mcma.sqlite3")
    with pytest.raises(CentralConfigurationError, match="does not exist"):
        create_central_server(settings, _test_only_portable_mutex=True)
    assert not (tmp_path / "nope").exists()


def test_missing_or_insecure_key_stops_startup_and_releases_the_lock(tmp_path):
    settings = central_settings(tmp_path)
    settings.session_vault_key_path.unlink()
    with pytest.raises(Exception, match="not found"):
        create_central_server(settings, _test_only_portable_mutex=True)
    # The lock taken before the failure was released: a retry gets past it.
    settings.session_vault_key_path.write_bytes(bytes(range(32)))
    import os

    if os.name == "posix":
        os.chmod(settings.session_vault_key_path, 0o600)
    create_central_server(settings, _test_only_portable_mutex=True).close()


def test_a_second_server_cannot_start_while_the_first_runs(tmp_path):
    first = _server(tmp_path)
    try:
        with pytest.raises(MutexAcquisitionError):
            _server(tmp_path)
    finally:
        first.close()


# ------------------------------- composition ----------------------------- #


def test_startup_provisions_the_four_accounts_and_never_reconciles_jobs(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("central startup must not reconcile local runner jobs")

    monkeypatch.setattr("mcma.execution.reconcile.reconcile_on_restart", forbidden)
    server = _server(tmp_path)
    try:
        assert server.api_conn.execute("SELECT COUNT(*) AS n FROM accounts").fetchone()["n"] == 4
    finally:
        server.close()


def test_central_composition_never_processes_jobs_or_launches_headful(
    tmp_path, forbid_job_processing, launcher
):
    server = _server(tmp_path)
    with _client(server) as client:
        assert client.get("/health").json()["notifications"] == "ready"
    assert forbid_job_processing == []
    assert [browser.headless for browser in launcher.launches] == [True]
    assert all(browser.closed for browser in launcher.launches)


def test_central_module_has_no_reference_to_execution_machinery():
    """Structural guard: the names are not merely uncalled, they are not
    present in the central composition root at all."""
    code = "\n".join(
        line for line in inspect.getsource(central_module).splitlines() if not line.lstrip().startswith("#")
    )
    # Strip the module docstring, which names these on purpose.
    code = code.split('"""', 2)[2]
    for forbidden in (
        "process_queued", "ActiveReviewRegistry", "RunnerConfig", "build_runner_config",
        "run_job_poll_loop", "mock_server", "local_settings", "headless=False",
    ):
        assert forbidden not in code, forbidden


def test_notification_polling_runs_through_the_extracted_service(tmp_path, launcher, monkeypatch):
    polls = []

    async def record(conn, browser, codes, **kwargs):
        polls.append(browser)
        return {}

    monkeypatch.setattr(service_module, "poll_all_accounts", record)
    server = _server(tmp_path)
    assert isinstance(server.notification_service, service_module.NotificationService)
    with _client(server):
        for _ in range(100):
            if polls:
                break
            import time

            time.sleep(0.02)
    assert polls and polls[0] is launcher.launches[0]


def test_shutdown_closes_browser_connections_and_releases_the_lock(tmp_path, launcher):
    server = _server(tmp_path)
    with _client(server) as client:
        assert client.get("/ready").status_code == 200
    assert server.notification_service.state is NotificationServiceState.STOPPED
    assert launcher.launches[0].closed
    with pytest.raises(Exception):
        server.api_conn.execute("SELECT 1")
    _server(tmp_path).close()  # lock is free again


# ---------------------------- auth boundaries --------------------------- #


def test_loopback_only_apps_are_not_mounted_on_the_lan_app(tmp_path, launcher):
    server = _server(tmp_path)
    paths = {getattr(route, "path", None) for route in server.app.routes}
    assert "/bootstrap-app" not in paths and "/onboarding-app" not in paths
    with _client(server) as client:   # even a loopback-looking client (reverse proxy on the same host)
        assert client.post("/bootstrap-app/bootstrap/tokens").status_code in (404, 405)
        assert client.post("/onboarding-app/anything").status_code in (404, 405)
        assert client.post(f"/accounts/{OUJDA}/login").status_code in (404, 405)  # no interactive login


def test_local_mode_still_mounts_the_loopback_apps(tmp_path):
    """Regression: the local composition is unchanged."""
    settings = Settings(
        db_path=tmp_path / "l.sqlite3", vault_dir=tmp_path / "v", dev_mode=True,
        allow_test_plaintext_job_inputs=True, allow_test_only_session_vault=True,
        mutex_name=f"mcma-local-{tmp_path.name}",
    )
    mutex, api_conn, _, encryptor = main_module.startup(settings, _test_only_portable_mutex=True)
    try:
        paths = {getattr(route, "path", None) for route in main_module.build_app(api_conn, settings, encryptor).routes}
        assert "/bootstrap-app" in paths and "/onboarding-app" in paths
    finally:
        mutex.release()


def test_no_automatic_authentication_and_csrf_still_applies(tmp_path, launcher):
    server = _server(tmp_path)
    with _client(server) as client:
        assert client.get("/accounts").status_code == 401     # loopback client, still refused
        server.api_conn.execute(
            "INSERT INTO users (user_id, username, password_hash, role, active) "
            "VALUES ('u1', 'agent', ?, 'operator', 1)", (hash_password("pw-for-tests"),),
        )
        server.api_conn.execute(
            "INSERT INTO user_account_access (user_id, account_id, granted_at) VALUES ('u1', ?, 'now')",
            (OUJDA,),
        )
        login = client.post("/auth/login", json={"username": "agent", "password": "pw-for-tests"})
        assert login.status_code == 200
        assert client.get("/accounts").status_code == 200
        # Authenticated, but a state change without the CSRF header is refused.
        assert client.post(f"/accounts/{OUJDA}/refresh-notifications").status_code in (400, 403)


def test_manual_refresh_uses_the_notification_browser(tmp_path, launcher, monkeypatch):
    seen = []

    async def fake_poll_one(conn, browser, account_id, codes, **kwargs):
        seen.append((browser, account_id, kwargs["allowed_host"]))
        return "POLLED"

    monkeypatch.setattr(composition_module, "poll_one_account", fake_poll_one)
    server = _server(tmp_path, notifications_enabled=False)  # background pass off; manual only
    with _client(server) as client:
        server.api_conn.execute(
            "INSERT INTO users (user_id, username, password_hash, role, active) "
            "VALUES ('u1', 'agent', ?, 'operator', 1)", (hash_password("pw-for-tests"),),
        )
        server.api_conn.execute(
            "INSERT INTO user_account_access (user_id, account_id, granted_at) VALUES ('u1', ?, 'now')",
            (OUJDA,),
        )
        csrf = client.post("/auth/login", json={"username": "agent", "password": "pw-for-tests"}).json()["csrf_token"]
        # The service retries/launches on its own; wait for the browser.
        for _ in range(100):
            if server.notification_service.browser is not None:
                break
            import time

            time.sleep(0.02)
        response = client.post(f"/accounts/{OUJDA}/refresh-notifications", headers={"X-CSRF-Token": csrf})
    assert response.status_code == 200 and response.json()["outcome"] == "POLLED"
    assert seen[0][0] is launcher.launches[0] and launcher.launches[0].headless is True
    assert seen[0][2] == "sinauto.mamda-mcma.ma"


# ------------------------------ health/readiness ------------------------ #


def test_health_reports_a_degraded_notification_browser_without_details(tmp_path, monkeypatch):
    failing = FakeLauncher(fail_times=99)
    monkeypatch.setattr(service_module, "launch_browser", failing)
    server = _server(tmp_path)
    with _client(server) as client:
        for _ in range(100):
            if server.notification_service.state is NotificationServiceState.DEGRADED:
                break
            import time

            time.sleep(0.02)
        health = client.get("/health").json()
        ready = client.get("/ready")
    assert health == {"status": "degraded", "db": True, "notifications": "degraded", "shutting_down": False}
    # Startup was NOT prevented, and the server still takes traffic.
    assert ready.status_code == 200 and ready.json()["ready"] is True
    assert "chromium" not in str(health).lower() and "chromium" not in ready.text.lower()


def test_not_ready_when_the_database_is_unavailable(tmp_path, launcher):
    server = _server(tmp_path)
    with _client(server) as client:
        server.api_conn.close()
        ready = client.get("/ready")
        health = client.get("/health").json()
    assert ready.status_code == 503 and ready.json()["ready"] is False
    assert health["db"] is False and health["status"] == "degraded"


def test_status_vocabulary():
    assert overall_status(True, "ready", False) == "ok"
    assert overall_status(True, "starting", False) == "starting"
    assert overall_status(True, "degraded", False) == "degraded"
    assert overall_status(False, "ready", False) == "degraded"
    assert overall_status(True, "ready", True) == "shutting_down"
    assert is_ready(True, False) and not is_ready(False, False) and not is_ready(True, True)


def test_health_reports_starting_before_the_browser_is_up(tmp_path):
    """Constructed but not yet served: the service has not launched."""
    server = _server(tmp_path)
    try:
        assert server.notification_service.state is NotificationServiceState.STARTING
    finally:
        server.close()


# ------------------- local composition regression (shared service) ------------------- #


def test_local_composition_still_processes_jobs_and_notifications(tmp_path, monkeypatch):
    launcher = FakeLauncher()
    monkeypatch.setattr(main_module, "launch_browser", launcher)
    monkeypatch.setattr(service_module, "launch_browser", launcher)
    jobs = {"dry": 0, "execute": 0}
    polled = []

    async def dry(conn, *, browser, cfg, encryptor):
        jobs["dry"] += 1

    async def execute(conn, *, browser, cfg, encryptor):
        jobs["execute"] += 1

    async def poll(conn, browser, codes, **kwargs):
        polled.append(browser)
        return {}

    monkeypatch.setattr(main_module, "process_queued_dry_run_jobs", dry)
    monkeypatch.setattr(main_module, "process_queued_planned_execute_jobs", execute)
    monkeypatch.setattr(service_module, "poll_all_accounts", poll)

    settings = Settings(
        db_path=tmp_path / "l.sqlite3", vault_dir=tmp_path / "v", dev_mode=True,
        allow_test_plaintext_job_inputs=True, allow_test_only_session_vault=True,
        poll_interval_seconds=0.01, notification_poll_interval_seconds=0.01,
    )
    supervisor = main_module.BrowserSupervisor()
    cfg = main_module.build_runner_config(settings)

    async def scenario():
        task = asyncio.create_task(
            main_module.run_job_poll_loop(object(), cfg, object(), settings, supervisor)
        )
        await supervisor.wait_until_ready(5)
        await asyncio.sleep(0.15)
        assert supervisor.get_notification() is launcher.launches[1]
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert jobs["dry"] >= 1 and jobs["execute"] >= 1
    assert polled and all(browser is launcher.launches[1] for browser in polled)
    # Visible browser first (headful), then the headless notification browser.
    assert [browser.headless for browser in launcher.launches] == [False, True]
    assert all(browser.closed for browser in launcher.launches)
