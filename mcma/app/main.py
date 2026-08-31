"""
mcma.app.main -- the composition root: the one place the whole system is
assembled into a running process.

Three modules already referred to this module as though it existed
(mcma.execution.runner twice, mcma.portal.pilot_contracts once) and
deploy/serve.md documented its five-step startup sequence, but no such
module was ever written -- so every part of the rebuilt system was
individually built and tested while the assembled application had no
entry point at all. In particular NOTHING called the runner's poll
functions, so a submitted job would sit at QUEUED forever no matter how
long the service ran.

Startup sequence (deploy/serve.md), in this exact order:

  1. Acquire the OS single-instance mutex -- fail closed if already held.
     INC-11's single-writer model is what makes the shared sqlite
     connection and the account-lease design safe; a second process must
     refuse to start rather than race the first.
  2. open_database() -- connect + forward-only migrations.
  3. reconcile_on_restart() -- BEFORE serving any request, so a job left
     mid-write by a crash is landed truthfully rather than being served
     (or resumed) as though it were still in flight.
  4. Build the authenticated API app, mount the dashboard and the two
     loopback-only sub-apps (first-admin bootstrap, session onboarding).
  5. serve() -- validates the TLS cert/key (fail closed) and starts the
     single Uvicorn worker over HTTPS only.

The runner is started from the app's lifespan rather than as a separate
process or thread: Playwright's async API is bound to the loop it was
started on, and mcma.execution.runner explicitly owns no loop of its own.
Running the poll loop on Uvicorn's own loop is what lets one browser
serve both the runner and the human handoff.

TWO CONNECTIONS, deliberately. The API gets one and the runner gets its
own. mcma.persistence.db.connect's docstring warns that sharing one
connection is safe only "as long as callers never share ONE connection
across genuinely concurrent writers without serializing access" -- and
six API endpoints are sync `def`, which Starlette dispatches onto a
worker THREAD while the runner's poll loop runs on the event loop. Both
transition() and acquire_lease() open BEGIN IMMEDIATE transactions, and a
second BEGIN IMMEDIATE on a connection already inside one raises
outright. WAL mode (enabled by connect()) is what makes two connections
to one database file the correct answer here rather than a workaround.
"""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from typing import Optional

from mcma.app.api.app import create_api_app
from mcma.app.auth.bootstrap import create_bootstrap_app
from mcma.app.auth.provider import LocalUserAuthProvider
from mcma.app.dashboard import mount_dashboard
from mcma.app.onboarding import create_onboarding_app
from mcma.app.provisioning import ensure_canonical_accounts, ensure_local_employee
from mcma.app.local_tls import ensure_local_certificate
from mcma.app.serve import TlsConfig, serve
from mcma.core.config import Settings, load_settings, require_dev_mode_is_safe
from mcma.core.mutex import create_single_instance_mutex
from mcma.execution.browser_handoff import ActiveReviewRegistry
from mcma.execution.inputs import InputEncryptor, get_input_encryptor
from mcma.execution.lease import acquire_account_lease
from mcma.execution.reconcile import reconcile_on_restart
from mcma.execution.runner import (
    RunnerConfig,
    process_queued_dry_run_jobs,
    process_queued_planned_execute_jobs,
)
from mcma.app.portal_login import capture_session_for_account
from mcma.notifications.poller import poll_all_accounts
from mcma.persistence.db import open_database
from mcma.portal.browser import launch_browser
from mcma.portal.vault import WindowsAclVerifier, get_crypto_backend


def _is_loopback(host: str) -> bool:
    from ipaddress import ip_address

    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


_DEV_TLS_DIR = Path("var") / "tls"


def build_encryptor(settings: Settings) -> InputEncryptor:
    """The production DPAPI-backed InputEncryptor does not exist yet --
    get_input_encryptor() raises ProductionEncryptorUnavailable rather
    than falling back to a weak one, which is the correct behaviour and
    is NOT worked around here. dev_mode explicitly selects the test-only
    plaintext encryptor, and require_dev_mode_is_safe() has already
    refused that combination against anything but the loopback mock."""
    return get_input_encryptor(_test_only_plaintext_backend=settings.dev_mode)


def build_app(conn, settings: Settings, encryptor: InputEncryptor, *, lifespan=None, browser_holder=None):
    """Assembles the one ASGI app: authenticated API + dashboard + the two
    loopback-only sub-apps. The sub-apps enforce their own loopback checks
    internally (mcma.app.auth.bootstrap._require_loopback,
    mcma.app.onboarding._require_loopback), so mounting them on the same
    LAN-served app does not expose them to the LAN."""
    async def _open_portal_login(account_id: str) -> str:
        """Runs the login capture on the process's ONE browser -- the same
        one the runner uses -- so the window the employee signs into is a
        real, visible browser on their own machine."""
        browser = browser_holder.get("browser") if browser_holder else None
        if browser is None:
            raise RuntimeError("no browser is available yet")
        return await capture_session_for_account(
            conn, browser, account_id,
            instance_id=settings.instance_id,
            allowed_host=settings.portal_host,
            vault_dir=settings.vault_dir,
            crypto_backend=get_crypto_backend(_test_only_in_memory_backend=settings.dev_mode),
            acl_verifier=WindowsAclVerifier(),
        )

    local_user_id = None
    if settings.local_single_user_mode:
        if not _is_loopback(settings.api_host):
            # Refused at startup rather than per request: a LAN-bound
            # install with this enabled would serve an authenticated
            # session to anyone who could reach the port.
            raise ValueError(
                "local_single_user_mode requires a loopback api_host; "
                f"refusing to start bound to {settings.api_host!r}"
            )
        local_user_id = ensure_local_employee(conn)

    app = create_api_app(
        conn,
        auth_provider=LocalUserAuthProvider(conn),
        encryptor=encryptor,
        secure_cookies=True,
        portal_login_opener=_open_portal_login if browser_holder is not None else None,
        local_user_id=local_user_id,
    )
    if lifespan is not None:
        app.router.lifespan_context = lifespan
    mount_dashboard(app)

    app.mount("/bootstrap-app", create_bootstrap_app(conn))

    def _lease_provider(account_id: str):
        # The onboarding endpoint never acquires a lease itself; it only
        # asserts the one it is handed is valid immediately before
        # replacing a session.
        return acquire_account_lease(conn, account_id, settings.instance_id)

    app.mount(
        "/onboarding-app",
        create_onboarding_app(
            conn=conn,
            vault_dir=settings.vault_dir,
            backend=get_crypto_backend(_test_only_in_memory_backend=settings.dev_mode),
            acl_verifier=WindowsAclVerifier(),
            lease_provider=_lease_provider,
        ),
    )
    return app


async def run_job_poll_loop(
    conn, cfg: RunnerConfig, encryptor: InputEncryptor, settings: Settings, browser_holder=None
) -> None:
    """Drains QUEUED DRY_RUN jobs and PLANNED EXECUTE jobs forever, on the
    caller's event loop, until cancelled at shutdown.

    One browser serves every job and the human handoff that follows: the
    review window an employee is still using belongs to this browser, so
    it must outlive any individual job and is closed only when the process
    stops.

    A failure inside a poll pass is logged-by-return, never fatal: both
    poll functions already isolate and land per-job failures truthfully
    (fail_closed_on_runner_exception), so an exception escaping to here
    means something outside any single job went wrong. The loop keeps
    running -- stopping it would silently strand every future job -- but
    it never retries faster than the poll interval."""
    async with launch_browser(headless=settings.headless_browser) as browser:
        # Published so the portal-login endpoint can open its window on
        # this same browser rather than starting a second one.
        if browser_holder is not None:
            browser_holder["browser"] = browser
        since_notification_poll = settings.notification_poll_interval_seconds
        while True:
            try:
                await process_queued_dry_run_jobs(conn, browser=browser, cfg=cfg, encryptor=encryptor)
                await process_queued_planned_execute_jobs(conn, browser=browser, cfg=cfg, encryptor=encryptor)

                # Notifications refresh on their own, much slower clock.
                # Jobs come first every pass: a notification refresh takes
                # an account's lease briefly, and a dossier someone is
                # waiting on must never queue behind one.
                since_notification_poll += settings.poll_interval_seconds
                if (settings.notification_category_codes
                        and since_notification_poll >= settings.notification_poll_interval_seconds):
                    since_notification_poll = 0
                    await poll_all_accounts(
                        conn, browser, settings.notification_category_codes,
                        instance_id=settings.instance_id,
                        allowed_host=settings.portal_host,
                        vault_dir=settings.vault_dir,
                        crypto_backend=cfg.crypto_backend,
                    )
            except asyncio.CancelledError:
                raise
            except Exception:
                pass
            await asyncio.sleep(settings.poll_interval_seconds)


def build_runner_config(settings: Settings) -> RunnerConfig:
    return RunnerConfig(
        instance_id=settings.instance_id,
        allowed_host=settings.allowed_host,
        vault_dir=settings.vault_dir,
        crypto_backend=get_crypto_backend(_test_only_in_memory_backend=settings.dev_mode),
        active_review_registry=ActiveReviewRegistry(),
    )


def build_tls_config(settings: Settings) -> TlsConfig:
    if settings.tls_cert_path is None or settings.tls_key_path is None:
        # serve() would refuse anyway; saying so here names the missing
        # setting instead of failing inside the TLS loader.
        raise ValueError(
            "tls_cert_path and tls_key_path must both be configured -- there is no "
            "plaintext HTTP fallback (deploy/serve.md, ADR-0008). For a local run see "
            "tools/dev_certificate.py."
        )
    return TlsConfig(
        cert_path=settings.tls_cert_path,
        key_path=settings.tls_key_path,
        host=settings.api_host,
        port=settings.api_port,
        subnet_allowlist=settings.subnet_allowlist,
    )


def startup(settings: Optional[Settings] = None, *, _test_only_portable_mutex: bool = False):
    """Steps 1-3: mutex, database, restart reconciliation. Returns
    (mutex, api_conn, runner_conn, encryptor) with the mutex already held.
    Split out from main() so it is testable without serving."""
    settings = settings or load_settings()
    require_dev_mode_is_safe(settings)

    mutex = create_single_instance_mutex(
        settings.mutex_name, _test_only_portable_backend=_test_only_portable_mutex
    )
    mutex.acquire()
    try:
        encryptor = build_encryptor(settings)
        api_conn = open_database(Path(settings.db_path))
        ensure_canonical_accounts(api_conn)
        reconcile_on_restart(api_conn, encryptor=encryptor)
        runner_conn = open_database(Path(settings.db_path))
    except Exception:
        mutex.release()
        raise
    return mutex, api_conn, runner_conn, encryptor


def local_settings() -> Settings:
    """The settings a single-office install runs with. This is what
    `python -m mcma.app.main` uses, so normal use needs no arguments, no
    bootstrap token and no separate launcher.

    dev_mode stays TRUE and allowed_host stays loopback: job inputs are
    still stored through the test-only plaintext encryptor because the
    DPAPI one does not exist yet (INC-21), and require_dev_mode_is_safe()
    refuses to start if that is ever combined with a non-loopback write
    target. Logging in and reading notifications go to the real portal
    (portal_host) -- neither can alter a claim."""
    base = Settings()
    return Settings(
        db_path=base.db_path,
        vault_dir=base.vault_dir,
        api_host="127.0.0.1",
        api_port=8443,
        tls_cert_path=_DEV_TLS_DIR / "local.crt",
        tls_key_path=_DEV_TLS_DIR / "local.key",
        dev_mode=True,
        local_single_user_mode=True,
        headless_browser=False,
        notification_category_codes=base.notification_category_codes,
    )


def main(settings: Optional[Settings] = None) -> None:  # pragma: no cover - real server loop
    settings = settings or local_settings()
    if settings.tls_cert_path is not None and not Path(settings.tls_cert_path).is_file():
        # HTTPS is the only listener there is (ADR-0008), so a missing
        # certificate would simply stop the application. Generating one
        # for loopback is not a security decision the employee should
        # have to make.
        ensure_local_certificate(Path(settings.tls_cert_path), Path(settings.tls_key_path))
    mutex, api_conn, runner_conn, encryptor = startup(settings)
    cfg = build_runner_config(settings)
    tls_config = build_tls_config(settings)

    browser_holder: dict = {}

    @contextlib.asynccontextmanager
    async def _lifespan(app):
        task = asyncio.create_task(
            run_job_poll_loop(runner_conn, cfg, encryptor, settings, browser_holder)
        )
        try:
            yield
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    app = build_app(api_conn, settings, encryptor, lifespan=_lifespan, browser_holder=browser_holder)
    try:
        serve(app, tls_config)
    finally:
        mutex.release()


if __name__ == "__main__":  # pragma: no cover
    print()
    print("=" * 68)
    print("  MCMA - Plateforme Sinistres")
    print("=" * 68)
    print("  Tableau de bord : https://127.0.0.1:8443/")
    print("  Portail         : https://sinauto.mamda-mcma.ma")
    print()
    print("  Votre navigateur signalera le certificat local : acceptez-le.")
    print("=" * 68)
    print()
    main()
