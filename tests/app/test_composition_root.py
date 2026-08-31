"""
Tests for mcma.app.main -- the composition root.

The gap these close is not a subtle one: until this module existed the
system had no entry point at all, nothing ever called the runner's poll
functions, and no test asserted that either fact was a problem. Every
increment was individually green while the assembled application could
not start.
"""

from pathlib import Path

import pytest

from mcma.app.main import (
    build_app,
    build_encryptor,
    build_runner_config,
    build_tls_config,
    startup,
)
from mcma.core.config import Settings, UnsafeDevModeConfiguration, require_dev_mode_is_safe
from mcma.execution.inputs import ProductionEncryptorUnavailable
from mcma.persistence.repositories.jobs import AutomationJobsRepository


def _dev_settings(tmp_path: Path, **overrides) -> Settings:
    defaults = dict(
        db_path=tmp_path / "mcma.sqlite3",
        vault_dir=tmp_path / "vault",
        dev_mode=True,
        allowed_host="127.0.0.1:8080",
        mutex_name=f"mcma-test-{tmp_path.name}",
    )
    defaults.update(overrides)
    return Settings(**defaults)


# --------------------------------------------------------------------- #
# dev_mode may never be pointed at anything but the mock portal
# --------------------------------------------------------------------- #


def test_dev_mode_against_a_non_loopback_host_refuses_to_start(tmp_path):
    """dev_mode stores CONTAINS_PII job inputs through the TEST-ONLY
    plaintext encryptor. Combining it with a live host would put real
    dossier PII on disk in cleartext, so the combination fails closed
    before the database is even opened."""
    settings = _dev_settings(tmp_path, allowed_host="sinauto.mamda-mcma.ma")
    with pytest.raises(UnsafeDevModeConfiguration):
        require_dev_mode_is_safe(settings)
    with pytest.raises(UnsafeDevModeConfiguration):
        startup(settings, _test_only_portable_mutex=True)
    # Nothing was created on the way to refusing.
    assert not (tmp_path / "mcma.sqlite3").exists()


@pytest.mark.parametrize(
    "host", ["127.0.0.1:8080", "[::1]:8080", "127.0.0.1:9999"]
)
def test_dev_mode_is_permitted_against_loopback(tmp_path, host):
    require_dev_mode_is_safe(_dev_settings(tmp_path, allowed_host=host))


def test_dev_mode_check_rejects_hostnames_that_merely_look_local(tmp_path):
    """"localhost" is a name requiring resolution, not a loopback
    literal -- the same distinction mcma.portal.writer._require_loopback_
    host already makes."""
    with pytest.raises(UnsafeDevModeConfiguration):
        require_dev_mode_is_safe(_dev_settings(tmp_path, allowed_host="localhost:8080"))


def test_production_mode_still_has_no_input_encryptor(tmp_path):
    """Guards against 'fixing' the missing DPAPI encryptor by quietly
    letting production fall through to the plaintext one. Production must
    keep failing closed until a real encryptor exists (INC-21)."""
    with pytest.raises(ProductionEncryptorUnavailable):
        build_encryptor(_dev_settings(tmp_path, dev_mode=False))


# --------------------------------------------------------------------- #
# Startup sequence
# --------------------------------------------------------------------- #


def test_startup_opens_the_database_and_runs_reconciliation(tmp_path):
    settings = _dev_settings(tmp_path)
    mutex, api_conn, runner_conn, encryptor = startup(settings, _test_only_portable_mutex=True)
    try:
        # Migrations ran.
        tables = {
            row["name"]
            for row in api_conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert "automation_jobs" in tables
        assert "account_leases" in tables
        # Canonical accounts were provisioned.
        accounts = api_conn.execute("SELECT account_id FROM accounts").fetchall()
        assert len(accounts) >= 1
    finally:
        mutex.release()


def test_startup_gives_the_runner_its_own_connection(tmp_path):
    """Not cosmetic: six API endpoints are sync `def`, which Starlette
    dispatches onto a worker thread while the runner polls on the event
    loop. transition() and acquire_lease() both use BEGIN IMMEDIATE, and
    a second BEGIN IMMEDIATE on a connection already inside one raises."""
    settings = _dev_settings(tmp_path)
    mutex, api_conn, runner_conn, _ = startup(settings, _test_only_portable_mutex=True)
    try:
        assert api_conn is not runner_conn
        # Both genuinely see the same database.
        api_conn.execute("BEGIN IMMEDIATE")
        api_conn.execute("COMMIT")
        runner_conn.execute("BEGIN IMMEDIATE")
        runner_conn.execute("COMMIT")
        assert (
            runner_conn.execute("SELECT count(*) AS n FROM accounts").fetchone()["n"]
            == api_conn.execute("SELECT count(*) AS n FROM accounts").fetchone()["n"]
        )
    finally:
        mutex.release()


def test_a_second_instance_cannot_start_while_the_first_holds_the_mutex(tmp_path):
    """INC-11's single-writer model is what makes the lease design and
    the two-connection split safe. A double-launch must refuse, not race."""
    settings = _dev_settings(tmp_path)
    mutex, _, _, _ = startup(settings, _test_only_portable_mutex=True)
    try:
        with pytest.raises(Exception):
            startup(settings, _test_only_portable_mutex=True)
    finally:
        mutex.release()


def test_startup_releases_the_mutex_if_a_later_step_fails(tmp_path):
    """A failure after the mutex is acquired must not leave the machine
    unable to start the service again."""
    settings = _dev_settings(tmp_path, db_path=tmp_path / "nope" / "\0bad")
    with pytest.raises(Exception):
        startup(settings, _test_only_portable_mutex=True)
    # The mutex is free: a subsequent well-formed startup succeeds.
    mutex, _, _, _ = startup(_dev_settings(tmp_path), _test_only_portable_mutex=True)
    mutex.release()


def test_reconciliation_runs_before_anything_is_served(tmp_path):
    """A job left mid-write by a crash must be landed truthfully by
    startup, not served as though it were still in flight."""
    settings = _dev_settings(tmp_path)
    mutex, api_conn, _, encryptor = startup(settings, _test_only_portable_mutex=True)
    account_id = api_conn.execute("SELECT account_id FROM accounts").fetchone()["account_id"]
    api_conn.execute(
        "INSERT INTO users (user_id, username, password_hash, role, active) "
        "VALUES ('op', 'op', 'x', 'OPERATOR', 1)"
    )
    job_id = "crashed-job"
    api_conn.execute(
        "INSERT INTO automation_jobs (job_id, account_id, requested_by_user_id, workflow_name, "
        "mode, status, input_hash, idempotency_key, created_at, state_version) "
        "VALUES (?, ?, 'op', 'MODE_NORMAL', 'EXECUTE', 'WRITING', 'h', 'k', "
        "'2026-01-01T00:00:00+00:00', 1)",
        (job_id, account_id),
    )
    mutex.release()

    mutex2, api_conn2, _, _ = startup(settings, _test_only_portable_mutex=True)
    try:
        status = AutomationJobsRepository(api_conn2).get(job_id)["status"]
        assert status == "INTERRUPTED_NEEDS_HUMAN_REVIEW"
    finally:
        mutex2.release()


# --------------------------------------------------------------------- #
# App assembly
# --------------------------------------------------------------------- #


def test_build_app_exposes_the_api_dashboard_and_loopback_subapps(tmp_path):
    settings = _dev_settings(tmp_path)
    mutex, api_conn, _, encryptor = startup(settings, _test_only_portable_mutex=True)
    try:
        app = build_app(api_conn, settings, encryptor)
        paths = {getattr(route, "path", None) for route in app.routes}
        assert "/health" in paths
        assert "/jobs" in paths
        assert "/events" in paths
        assert "/" in paths                    # dashboard index
        assert "/bootstrap-app" in paths       # first-admin, loopback-only
        assert "/onboarding-app" in paths      # session capture, loopback-only
    finally:
        mutex.release()


def test_runner_config_carries_the_settings_the_runner_needs(tmp_path):
    settings = _dev_settings(tmp_path)
    cfg = build_runner_config(settings)
    assert cfg.instance_id == settings.instance_id
    assert cfg.allowed_host == settings.allowed_host
    assert cfg.vault_dir == settings.vault_dir
    assert cfg.active_review_registry.active_job_count() == 0


def test_tls_is_required_with_no_plaintext_fallback(tmp_path):
    """ADR-0008: there is no HTTP path. An unconfigured cert must stop
    startup, never silently serve plaintext."""
    with pytest.raises(ValueError):
        build_tls_config(_dev_settings(tmp_path))

    configured = _dev_settings(
        tmp_path, tls_cert_path=tmp_path / "c.crt", tls_key_path=tmp_path / "k.key"
    )
    tls = build_tls_config(configured)
    assert tls.cert_path == tmp_path / "c.crt"
    assert tls.port == configured.api_port


# --------------------------------------------------------------------- #
# Zero-argument local startup
# --------------------------------------------------------------------- #


def test_local_settings_are_safe_and_need_no_arguments():
    """`python -m mcma.app.main` must start a single-office install with
    no bootstrap token, no launcher and no arguments -- while keeping the
    two properties that make dev_mode acceptable: form filling stays on
    loopback, and the write target is never the real portal."""
    from mcma.app.main import local_settings
    from mcma.core.config import require_dev_mode_is_safe

    settings = local_settings()
    assert settings.local_single_user_mode is True
    assert settings.dev_mode is True
    assert settings.api_host == "127.0.0.1"
    assert settings.headless_browser is False       # the human must see the handoff
    assert settings.tls_cert_path is not None       # HTTPS only, no plaintext path
    # Writing stays on the mock; logging in and reading go to the portal.
    require_dev_mode_is_safe(settings)
    assert settings.allowed_host.startswith("127.0.0.1")
    assert settings.portal_host == "sinauto.mamda-mcma.ma"


def test_notification_ingestion_is_off_until_it_is_configured():
    """INC-14: production notification ingestion "defaults unavailable"
    until G-PDR (INC-20 + INC-21). An empty category list means no poll
    ever runs, so real claimant data cannot be persisted by accident."""
    from mcma.app.main import local_settings

    assert local_settings().notification_category_codes == ()


def test_the_local_certificate_is_generated_and_actually_usable(tmp_path):
    from mcma.app.local_tls import ensure_local_certificate
    from mcma.app.serve import TlsConfig, build_ssl_context

    cert, key = tmp_path / "local.crt", tmp_path / "local.key"
    ensure_local_certificate(cert, key)
    assert cert.is_file() and key.is_file()
    # Proven usable by the real server loader, not merely present on disk.
    build_ssl_context(TlsConfig(cert_path=cert, key_path=key))

    # An existing pair is never overwritten.
    before = cert.read_bytes()
    ensure_local_certificate(cert, key)
    assert cert.read_bytes() == before
