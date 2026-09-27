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
  4. Build the authenticated API app, mount the built employee UI
     (frontend/dist) and the two loopback-only sub-apps (first-admin
     bootstrap, session onboarding).
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
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

from mcma.app.browser_supervisor import BrowserSupervisor, BrowserUnavailable
# Shared with the central server; re-exported so existing callers of
# mcma.app.main.build_app etc. are unchanged.
from mcma.app.composition import (  # noqa: F401
    build_app,
    build_encryptor,
    build_session_backend,
    build_tls_config,
    make_session_observer,
)
from mcma.app.provisioning import ensure_canonical_accounts
from mcma.app.local_tls import ensure_local_certificate
from mcma.app.serve import serve
from mcma.app.windows_socket_noise import quiet_benign_connection_resets
from mcma.core.config import Settings, load_settings, require_dev_mode_is_safe
from mcma.core.mutex import create_single_instance_mutex
from mcma.execution.browser_handoff import ActiveReviewRegistry
from mcma.execution.inputs import InputEncryptor
from mcma.execution.reconcile import reconcile_on_restart
from mcma.execution.runner import (
    RunnerConfig,
    process_queued_dry_run_jobs,
    process_queued_planned_execute_jobs,
)
from mcma.app.connection_state import ConnectionStateTracker
from mcma.notifications.service import NotificationService
from mcma.persistence.db import open_database
from mcma.portal.browser import launch_browser
from mcma.portal.vault import CryptoBackend

_DEV_TLS_DIR = Path("var") / "tls"


async def run_job_poll_loop(
    conn, cfg: RunnerConfig, encryptor: InputEncryptor, settings: Settings,
    supervisor: "BrowserSupervisor | None" = None,
    session_observer=None,
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
    try:
        browser_context = launch_browser(headless=settings.headless_browser)
        browser = await browser_context.__aenter__()
    except Exception as exc:
        # A launch failure must reach startup, not die inside this task.
        if supervisor is not None:
            supervisor.mark_failed(exc)
        raise

    # Notification polling is the shared NotificationService (also used by
    # the central server): a SECOND, headless, long-lived browser owned by
    # the service, never a fallback to the visible one above. Its failure
    # is not fatal to the application, but it IS fatal to notification
    # refresh: refreshes then fail visibly instead of flashing a window.
    notification_service = NotificationService(
        conn, settings,
        crypto_backend=cfg.crypto_backend,
        session_observer=session_observer,
        on_browser_ready=supervisor.mark_notification_ready if supervisor is not None else None,
        on_browser_lost=supervisor.mark_notification_lost if supervisor is not None else None,
    )
    await notification_service.start()

    try:
        # Published here, once, so login, notification reads, the dossier
        # runner and the human handoff all share ONE browser.
        if supervisor is not None:
            supervisor.mark_ready(browser)
        while True:
            try:
                await process_queued_dry_run_jobs(conn, browser=browser, cfg=cfg, encryptor=encryptor)
                await process_queued_planned_execute_jobs(conn, browser=browser, cfg=cfg, encryptor=encryptor)

                # Notifications refresh on their own, much slower clock.
                # Jobs come first every pass: a notification refresh takes
                # an account's lease briefly, and a dossier someone is
                # waiting on must never queue behind one.
                await notification_service.poll_if_due(settings.poll_interval_seconds)
            except asyncio.CancelledError:
                raise
            except Exception:
                # Per-job failures are already landed truthfully by the
                # poll functions themselves, so reaching here means
                # something outside any single job went wrong. The loop
                # keeps running -- stopping it would strand every future
                # job -- but the failure is reported rather than
                # swallowed.
                logger.exception("job poll pass failed")
            await asyncio.sleep(settings.poll_interval_seconds)
    finally:
        # The notification browser first: it owns no window an employee is
        # looking at, so nothing is lost by closing it early, and leaking
        # a headless Chromium keeps a driver process alive after the app
        # exits on Windows.
        await notification_service.stop()
        try:
            await browser_context.__aexit__(None, None, None)
        except Exception:
            # Teardown only. An exception raised here would REPLACE the
            # reason the loop actually ended -- a CancelledError on
            # shutdown, or a genuine failure -- and the real reason is
            # what matters. On Ctrl+C the driver connection is usually
            # already gone, so closing an already-dead browser reports an
            # error that is neither surprising nor actionable. It is
            # logged, never hidden, and never allowed to become the exit
            # reason. This is narrow to closing the browser; nothing
            # during normal runtime is suppressed.
            logger.info("shared browser was already gone at shutdown", exc_info=True)


def build_runner_config(
    settings: Settings, crypto_backend: Optional[CryptoBackend] = None
) -> RunnerConfig:
    return RunnerConfig(
        instance_id=settings.instance_id,
        allowed_host=settings.allowed_host,
        vault_dir=settings.vault_dir,
        crypto_backend=crypto_backend if crypto_backend is not None else build_session_backend(settings),
        active_review_registry=ActiveReviewRegistry(),
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

    dev_mode stays TRUE, meaning form filling targets the loopback mock
    (G5); logging in and reading notifications go to the real portal, and
    neither can alter a claim. Storage is REAL: dossier inputs are
    encrypted with DPAPI CURRENT_USER and portal sessions with the DPAPI
    vault, because the employee running this handles real dossiers even
    while writes are still pointed at the mock."""
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
        notifications_enabled=base.notifications_enabled,
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
    # One session backend for the whole process, shared by the runner,
    # the poller, manual refresh, login and onboarding.
    crypto_backend = build_session_backend(settings)
    cfg = build_runner_config(settings, crypto_backend)
    tls_config = build_tls_config(settings)

    supervisor = BrowserSupervisor()
    # One tracker for the whole process: the API reads what the poll loop
    # observes.
    connection_tracker = ConnectionStateTracker()

    @contextlib.asynccontextmanager
    async def _lifespan(app):
        # Removes ONE piece of Windows console noise for the life of the
        # application -- asyncio's proactor cleanup reset (WinError 10054)
        # after a browser drops a keep-alive or the /events stream. Every
        # other loop exception still reaches the previous/default handler,
        # and the previous handler is restored on shutdown.
        async with quiet_benign_connection_resets():
            task = asyncio.create_task(
                run_job_poll_loop(
                    runner_conn, cfg, encryptor, settings, supervisor,
                    session_observer=make_session_observer(connection_tracker),
                )
            )
            # Observed even if nothing ever awaits it, so a browser that dies
            # later cannot leave a healthy-looking dashboard behind.
            supervisor.watch(task)
            # The application does not accept traffic until the browser is up.
            # Serving first is what let a login click race startup and be
            # reported as a failed portal sign-in.
            try:
                await supervisor.wait_until_ready(settings.browser_startup_timeout_seconds)
            except BrowserUnavailable:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
                raise
            try:
                yield
            finally:
                # Declared BEFORE cancelling: from here on, a browser that
                # fails to close is an expected part of stopping, not a fault.
                supervisor.begin_shutdown()
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task

    app = build_app(api_conn, settings, encryptor, lifespan=_lifespan, supervisor=supervisor, connection_tracker=connection_tracker, crypto_backend=crypto_backend)
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
