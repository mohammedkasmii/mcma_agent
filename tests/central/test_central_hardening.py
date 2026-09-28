"""Phase 1 review fixes: runtime browser loss, startup filesystem checks,
secret-path hardening, one backend per process, and (Phase 1C-B central-
integration correction) EXECUTE job creation staying refused in central
mode while DRY_RUN creation is now enabled."""

import os
import sys
import time

import pytest
from fastapi.testclient import TestClient

import mcma.app.central_server as central_module
import mcma.app.composition as composition_module
import mcma.notifications.service as service_module
from central_test_support import KEY_A, FakeLauncher, central_settings, write_key
from mcma.app.auth.passwords import hash_password
from mcma.app.central_server import create_central_server
from mcma.core.central_config import CentralConfigurationError, validate_central_settings
from mcma.notifications.service import NotificationServiceState

OUJDA = "acct-mcma-oujda"
posix_only = pytest.mark.skipif(sys.platform == "win32", reason="POSIX ownership/permission semantics")

# A proven-valid minimal Wexia payload (tests/app/runners/dispatch_test_
# support.py's own VALID_TYPED_INPUT, duplicated here -- bounded
# duplication over a cross-directory import, the established INC-06+
# convention -- see that module's own docstring): parses via parse_wexia
# and resolves to a real, non-needs-review workflow, so a DRY_RUN created
# from it genuinely reaches QUEUED rather than failing WORKFLOW_NOT_
# DETERMINABLE.
_VALID_TYPED_INPUT = {
    "dossier": {
        "id_sinistre": "699001",
        "mission_type": "normal",
        "incident_description": "MODE NORMAL",
        "is_reform": False,
    },
    "vehicule": {"license_plate": "77001-C-3"},
    "chiffrages": [
        {
            "id": "CH-NORMAL-1",
            "status": "approved",
            "is_final": True,
            "scenario_type": "repair",
            "total_cost": 10,
            "tax_amount": 2,
            "lignes_pieces": [
                {"item_type": "part", "item_name": "pare-choc avant", "part_type": "original", "subtotal": 10}
            ],
        }
    ],
}


def _server(tmp_path, **overrides):
    return create_central_server(central_settings(tmp_path, **overrides), _test_only_portable_mutex=True)


def _client(server):
    return TestClient(server.app, base_url="https://testserver", client=("127.0.0.1", 5000))


def _wait(predicate, seconds=5.0):
    deadline = time.time() + seconds
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def _login(server, client):
    server.api_conn.execute(
        "INSERT INTO users (user_id, username, password_hash, role, active) "
        "VALUES ('u1', 'agent', ?, 'operator', 1)", (hash_password("pw-for-tests"),),
    )
    server.api_conn.execute(
        "INSERT INTO user_account_access (user_id, account_id, granted_at) VALUES ('u1', ?, 'now')", (OUJDA,),
    )
    response = client.post("/auth/login", json={"username": "agent", "password": "pw-for-tests"})
    assert response.status_code == 200
    return {"X-CSRF-Token": response.json()["csrf_token"]}


@pytest.fixture()
def launcher(monkeypatch):
    fake = FakeLauncher()
    monkeypatch.setattr(service_module, "launch_browser", fake)
    return fake


# ------------------------ runtime browser disconnection ------------------------ #


def test_runtime_disconnect_degrades_refuses_refresh_then_recovers(tmp_path, launcher, monkeypatch):
    polls, refreshes = [], []

    async def record_poll(conn, browser, codes, **kwargs):
        polls.append(browser)
        return {}

    async def record_refresh(conn, browser, account_id, codes, **kwargs):
        refreshes.append(browser)
        return "POLLED"

    monkeypatch.setattr(service_module, "poll_all_accounts", record_poll)
    monkeypatch.setattr(composition_module, "poll_one_account", record_refresh)
    server = _server(tmp_path, notification_poll_interval_seconds=0.02)

    with _client(server) as client:
        headers = _login(server, client)
        assert _wait(lambda: server.notification_service.state is NotificationServiceState.READY)
        first = launcher.launches[0]
        assert client.get("/health").json()["notifications"] == "ready"
        assert _wait(lambda: len(polls) >= 1) and polls[0] is first
        assert client.post(f"/accounts/{OUJDA}/refresh-notifications", headers=headers).status_code == 200

        # Chromium dies. Health changes at once; the dead handle is refused.
        first.disconnect()
        assert client.get("/health").json()["notifications"] == "degraded"
        assert client.get("/health").json()["status"] == "degraded"
        refused = client.post(f"/accounts/{OUJDA}/refresh-notifications", headers=headers)
        assert refused.status_code == 503
        assert refused.json()["error"] == "NOTIFICATION_BROWSER_UNAVAILABLE"
        assert refreshes == [first]                       # the dead browser was never used again

        # Automatic relaunch (retry delay shortened only now, so the
        # degraded window above is observable deterministically).
        monkeypatch.setattr(service_module, "BROWSER_RETRY_SECONDS", 0.05)
        # Automatic relaunch, back to READY, polls move to the replacement.
        assert _wait(lambda: server.notification_service.state is NotificationServiceState.READY)
        assert len(launcher.launches) == 2
        second = launcher.launches[1]
        assert second is not first and client.get("/health").json()["notifications"] == "ready"
        polls.clear()
        assert _wait(lambda: len(polls) >= 1) and all(browser is second for browser in polls)
        assert client.post(f"/accounts/{OUJDA}/refresh-notifications", headers=headers).status_code == 200
        assert refreshes[-1] is second

        # The stale context was cleaned up.
        assert first.closed is True and second.closed is False
        assert launcher.closed_contexts == 1

    assert second.closed is True
    assert launcher.closed_contexts == 2
    import asyncio

    asyncio.run(server.notification_service.stop())     # idempotent after shutdown
    assert server.notification_service.state is NotificationServiceState.STOPPED


def test_ordinary_polling_failures_do_not_degrade_a_connected_browser(tmp_path, launcher, monkeypatch):
    async def failing_poll(conn, browser, codes, **kwargs):
        raise RuntimeError("portal exploded")

    monkeypatch.setattr(service_module, "poll_all_accounts", failing_poll)
    server = _server(tmp_path, notification_poll_interval_seconds=0.02)
    with _client(server) as client:
        assert _wait(lambda: server.notification_service.state is NotificationServiceState.READY)
        time.sleep(0.3)   # many failing passes
        assert client.get("/health").json()["notifications"] == "ready"
    assert len(launcher.launches) == 1


def test_supervisor_never_returns_a_known_dead_browser():
    from mcma.app.browser_supervisor import BrowserSupervisor, BrowserUnavailable
    from central_test_support import FakeBrowser

    supervisor = BrowserSupervisor()
    browser = FakeBrowser(True)
    supervisor.mark_notification_ready(browser)
    assert supervisor.get_notification() is browser
    browser.disconnect()
    with pytest.raises(BrowserUnavailable):
        supervisor.get_notification()
    replacement = FakeBrowser(True)
    supervisor.mark_notification_ready(replacement)
    assert supervisor.get_notification() is replacement
    supervisor.mark_notification_lost()
    with pytest.raises(BrowserUnavailable):
        supervisor.get_notification()


# ------------------------------ POSIX vault check ------------------------------ #


@posix_only
@pytest.mark.parametrize("mode", [0o755, 0o770, 0o750, 0o707])
def test_vault_with_group_or_other_bits_is_refused_at_startup(tmp_path, mode):
    settings = central_settings(tmp_path)
    os.chmod(settings.vault_dir, mode)
    with pytest.raises(CentralConfigurationError, match="vault_dir"):
        create_central_server(settings, _test_only_portable_mutex=True)
    assert not settings.db_path.exists()      # refused before the database opened


@posix_only
def test_vault_symlink_is_refused(tmp_path):
    settings = central_settings(tmp_path)
    real = tmp_path / "real-vault"
    real.mkdir(mode=0o700)
    link = tmp_path / "vault-link"
    link.symlink_to(real)
    with pytest.raises(CentralConfigurationError, match="vault_dir"):
        create_central_server(central_settings(tmp_path, vault_dir=link), _test_only_portable_mutex=True)
    assert not settings.db_path.exists()


@posix_only
def test_vault_with_wrong_owner_is_refused(tmp_path, monkeypatch):
    settings = central_settings(tmp_path)
    monkeypatch.setattr(os, "geteuid", lambda: os.stat(settings.vault_dir).st_uid + 1)
    with pytest.raises(CentralConfigurationError, match="vault_dir"):
        create_central_server(settings, _test_only_portable_mutex=True)


def test_missing_or_non_directory_vault_is_refused_and_not_created(tmp_path):
    settings = central_settings(tmp_path)
    settings.vault_dir.rmdir()
    with pytest.raises(CentralConfigurationError, match="vault_dir must already exist"):
        create_central_server(settings, _test_only_portable_mutex=True)
    assert not settings.vault_dir.exists()
    (tmp_path / "vfile").write_text("x")
    with pytest.raises(CentralConfigurationError, match="vault_dir must already exist"):
        create_central_server(central_settings(tmp_path, vault_dir=tmp_path / "vfile"), _test_only_portable_mutex=True)


# ------------------------------ secret paths ----------------------------------- #


def test_tls_private_key_may_not_live_in_a_served_directory(tmp_path):
    served = composition_module.__file__  # anchor: repo root is derived from the package location
    from mcma.core.central_config import repository_served_dirs

    settings = central_settings(tmp_path, tls_key_path=repository_served_dirs()[0] / "server.key")
    with pytest.raises(CentralConfigurationError, match="tls_key_path must not be inside"):
        validate_central_settings(settings)
    assert served


def test_public_tls_certificate_may_sit_in_a_served_directory(tmp_path):
    from mcma.core.central_config import repository_served_dirs

    validate_central_settings(central_settings(tmp_path, tls_cert_path=repository_served_dirs()[0] / "server.crt"))


@posix_only
def test_tls_private_key_with_loose_permissions_or_owner_is_refused(tmp_path, monkeypatch):
    settings = central_settings(tmp_path)
    os.chmod(settings.tls_key_path, 0o640)
    with pytest.raises(CentralConfigurationError, match="tls_key_path"):
        create_central_server(settings, _test_only_portable_mutex=True)
    os.chmod(settings.tls_key_path, 0o600)
    monkeypatch.setattr(os, "geteuid", lambda: os.stat(settings.tls_key_path).st_uid + 1)
    with pytest.raises(CentralConfigurationError, match="tls_key_path"):
        create_central_server(settings, _test_only_portable_mutex=True)


def test_missing_tls_private_key_is_refused(tmp_path):
    settings = central_settings(tmp_path)
    settings.tls_key_path.unlink()
    with pytest.raises(CentralConfigurationError, match="tls_key_path"):
        create_central_server(settings, _test_only_portable_mutex=True)


def test_key_paths_are_compared_after_resolution(tmp_path):
    base = central_settings(tmp_path)
    spelled_differently = tmp_path / "secrets" / ".." / "secrets" / "session.key"
    with pytest.raises(CentralConfigurationError, match="different files"):
        validate_central_settings(central_settings(tmp_path, job_input_key_path=spelled_differently))
    assert base.session_vault_key_path.exists()


def test_symlink_alias_of_the_session_key_is_rejected(tmp_path):
    settings = central_settings(tmp_path)
    alias = tmp_path / "secrets" / "alias.key"
    try:
        alias.symlink_to(settings.session_vault_key_path)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not permitted here")
    with pytest.raises(CentralConfigurationError, match="different files"):
        validate_central_settings(central_settings(tmp_path, job_input_key_path=alias))


def test_hard_link_alias_of_the_session_key_is_rejected_at_startup(tmp_path):
    settings = central_settings(tmp_path)
    alias = tmp_path / "secrets" / "hard.key"
    os.link(settings.session_vault_key_path, alias)
    with pytest.raises(CentralConfigurationError, match="same file"):
        create_central_server(central_settings(tmp_path, job_input_key_path=alias), _test_only_portable_mutex=True)


def test_identical_key_bytes_in_different_files_are_rejected(tmp_path):
    settings = central_settings(tmp_path)
    twin = write_key(tmp_path / "secrets" / "twin.key", KEY_A)
    assert twin != settings.session_vault_key_path
    with pytest.raises(CentralConfigurationError, match="identical key material"):
        create_central_server(central_settings(tmp_path, job_input_key_path=twin), _test_only_portable_mutex=True)
    # Refused after the lock was taken and before the database was opened, and the lock was released.
    assert not settings.db_path.exists()
    create_central_server(settings, _test_only_portable_mutex=True).close()


# --------------------------- one backend per process --------------------------- #


def test_keys_are_read_once_and_one_backend_serves_every_consumer(tmp_path, launcher, monkeypatch):
    reads = []
    real_load = central_module.load_key_file
    monkeypatch.setattr(central_module, "load_key_file", lambda path: reads.append(path) or real_load(path))

    def forbidden(settings):
        raise AssertionError("a second backend was built")

    monkeypatch.setattr(composition_module, "build_session_backend", forbidden)
    monkeypatch.setattr("mcma.portal.vault.load_key_file", lambda path: (_ for _ in ()).throw(AssertionError("key reread")))
    seen = []

    async def record_refresh(conn, browser, account_id, codes, **kwargs):
        seen.append(kwargs["crypto_backend"])
        return "POLLED"

    monkeypatch.setattr(composition_module, "poll_one_account", record_refresh)
    server = _server(tmp_path, notifications_enabled=False)
    assert len(reads) == 2
    with _client(server) as client:
        headers = _login(server, client)
        assert _wait(lambda: server.notification_service.browser is not None)
        for _ in range(3):
            assert client.post(f"/accounts/{OUJDA}/refresh-notifications", headers=headers).status_code == 200
    assert len(reads) == 2
    assert len(seen) == 3 and all(backend is server.notification_service._crypto_backend for backend in seen)


def test_local_build_app_builds_its_backend_once_not_per_request(tmp_path, monkeypatch):
    from mcma.app.main import build_app, startup
    from mcma.core.config import Settings
    from mcma.portal.vault import TestOnlyInMemoryCryptoBackend

    built = []
    monkeypatch.setattr(
        composition_module, "build_session_backend", lambda s: built.append(1) or TestOnlyInMemoryCryptoBackend()
    )
    settings = Settings(
        db_path=tmp_path / "l.sqlite3", vault_dir=tmp_path / "v", dev_mode=True,
        allow_test_plaintext_job_inputs=True, allow_test_only_session_vault=True,
        mutex_name=f"mcma-local-{tmp_path.name}",
    )
    mutex, api_conn, _, encryptor = startup(settings, _test_only_portable_mutex=True)
    try:
        build_app(api_conn, settings, encryptor)
        assert built == [1]
        supplied = TestOnlyInMemoryCryptoBackend()
        build_app(api_conn, settings, encryptor, crypto_backend=supplied)
        assert built == [1]                       # a supplied backend is used as-is
    finally:
        mutex.release()


# ------------------------ Agent creation refused centrally ---------------------- #


def _all_counts(server):
    return tuple(
        server.api_conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
        for table in ("automation_jobs", "job_inputs", "audit_events", "event_outbox")
    )


def test_central_execute_posts_are_refused_with_a_typed_503_and_store_nothing(tmp_path, launcher):
    """Phase 1C-B central-integration correction: EXECUTE creation stays
    refused centrally -- checked before anything is read, stored or
    queued, so a disabled-mode request never partially writes a job, its
    encrypted input, an audit record or an outbox event. (DRY_RUN creation
    is now enabled centrally -- see
    test_central_dry_run_creation_succeeds_while_execute_stays_refused
    below.)"""
    server = _server(tmp_path)
    with _client(server) as client:
        headers = _login(server, client)
        before = _all_counts(server)
        body = {"account_id": OUJDA, "typed_input": {"claim": "PRIVATE-DOSSIER-DATA"}, "idempotency_key": "k1"}
        response = client.post("/jobs/some-dry-run/executions", json=body, headers=headers)
        assert response.status_code == 503
        assert response.json()["error"] == "RUNNER_CONTROL_PLANE_UNAVAILABLE"
        assert "PRIVATE-DOSSIER-DATA" not in response.text
        # No partial write of any kind -- not the job row, not an input,
        # not an audit record, not an outbox event. (audit_events/
        # event_outbox may already hold rows from login/startup; only the
        # DELTA across this refused request matters here.)
        assert _all_counts(server) == before

        # Still authenticated/CSRF-protected, and reads stay available.
        assert client.post("/jobs/dry-runs", json={}).status_code in (400, 403)
        assert client.get("/jobs").status_code == 200
        assert client.get("/accounts").status_code == 200
        assert client.get("/notifications").status_code == 200


def test_central_dry_run_creation_succeeds_while_execute_stays_refused(tmp_path, launcher):
    """Phase 1C-B central-integration correction: an authenticated,
    authorized employee can now create an MCMA DRY_RUN centrally -- the
    row lands DRY_RUN/QUEUED, exactly one job and one encrypted input are
    stored, and EXECUTE creation against that SAME (real, existing) job
    still returns the fixed 503 -- never bypassed just because a genuine
    DRY_RUN now exists to reference."""
    server = _server(tmp_path)
    with _client(server) as client:
        headers = _login(server, client)
        before = _all_counts(server)
        body = {"account_id": OUJDA, "typed_input": _VALID_TYPED_INPUT, "idempotency_key": "central-dry-run-1"}
        created = client.post("/jobs/dry-runs", json=body, headers=headers)
        assert created.status_code == 200, created.text
        job_id = created.json()["job_id"]
        assert created.json()["status"] == "QUEUED"

        row = server.api_conn.execute(
            "SELECT mode, status FROM automation_jobs WHERE job_id = ?", (job_id,)
        ).fetchone()
        assert (row["mode"], row["status"]) == ("DRY_RUN", "QUEUED")
        after_dry_run = _all_counts(server)
        assert after_dry_run[0] == before[0] + 1  # exactly one job
        assert after_dry_run[1] == before[1] + 1  # exactly one encrypted input -- nothing extra

        execution = client.post(f"/jobs/{job_id}/executions", json={}, headers=headers)
        assert execution.status_code == 503
        assert execution.json()["error"] == "RUNNER_CONTROL_PLANE_UNAVAILABLE"
        assert server.api_conn.execute(
            "SELECT COUNT(*) AS n FROM automation_jobs WHERE mode = 'EXECUTE'"
        ).fetchone()["n"] == 0
        # The refused EXECUTE attempt itself wrote nothing further -- job/
        # input counts are exactly what the DRY_RUN alone produced.
        assert _all_counts(server)[:2] == after_dry_run[:2]


def test_local_agent_creation_is_unchanged(tmp_path):
    """Default composition: the same endpoint runs its normal validation
    (400 for a bad body), not the central refusal."""
    from mcma.app.api.app import create_api_app
    from mcma.app.auth.provider import LocalUserAuthProvider
    from mcma.app.auth.sessions import SessionStore
    from mcma.execution.inputs import TestOnlyPlaintextEncryptor
    from mcma.persistence.db import open_database

    conn = open_database(tmp_path / "l.sqlite3")
    from mcma.app.provisioning import ensure_canonical_accounts

    ensure_canonical_accounts(conn)
    conn.execute(
        "INSERT INTO users (user_id, username, password_hash, role, active) "
        "VALUES ('u1', 'agent', ?, 'operator', 1)", (hash_password("pw-for-tests"),),
    )
    app = create_api_app(
        conn, auth_provider=LocalUserAuthProvider(conn), session_store=SessionStore(),
        encryptor=TestOnlyPlaintextEncryptor(), secure_cookies=False,
    )
    client = TestClient(app, client=("127.0.0.1", 1))
    csrf = client.post("/auth/login", json={"username": "agent", "password": "pw-for-tests"}).json()["csrf_token"]
    response = client.post("/jobs/dry-runs", json={}, headers={"X-CSRF-Token": csrf})
    assert response.status_code == 400
    assert response.json()["error"] == "BAD_REQUEST"
