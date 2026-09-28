"""
mcma.app.central_server -- the composition root of the CENTRAL agency
server (Ubuntu). Phase 1 of the central-server / workstation-runner
architecture; see docs/architecture/CENTRAL_SERVER_DEPLOYMENT.md.

What this process is:  API + built frontend + central SQLite database +
the four server-side notification sessions, polled headlessly.

What it deliberately is NOT -- each of these is absent by construction,
not merely switched off, and tests/app/test_central_server.py pins them:

  * no job processing: neither process_queued_dry_run_jobs nor
    process_queued_planned_execute_jobs is imported or called here;
    dossier form filling belongs to the Windows workstation runners;
  * no visible / form-filling browser and no ActiveReviewRegistry -- the
    only browser is the headless notification browser owned by
    mcma.notifications.service.NotificationService;
  * no mock portal, and no execution target: RunnerConfig is never built,
    so allowed_host (the loopback mock in local mode) is never used;
  * no interactive portal login (it would need a display) and no
    loopback-only bootstrap/onboarding sub-apps -- behind a reverse proxy
    on the same host every request looks like loopback, so those apps are
    not mounted at all;
  * no local automatic single-user authentication.

Startup order (each step fails closed; nothing is served on any failure):

  1. validate_central_settings()  -- unsafe/missing configuration stops here
  2. TLS certificate/key validated -- there is no plaintext listener
  3. single-instance lock         -- a second server refuses to start
  4. encryption keys loaded       -- missing/insecure/short key stops here
  5. open_database() + canonical account provisioning (forward-only
     migrations run inside open_database)
  6. build the app; the notification service starts INSIDE the ASGI
     lifespan, in the background

reconcile_on_restart is intentionally NOT run: it lands jobs left
mid-write by a crashed LOCAL runner, and in the central topology jobs will
be executed by workstations that outlive a server restart.

Shutdown: the poll task is cancelled, the headless browser is closed, both
database connections are closed and the lock released -- in that order.

Notification-browser failure does not stop startup. The server starts,
reports `notifications: degraded` on /health, keeps serving employees, and
the service retries the browser launch at every poll interval. See
mcma.app.server_status for the reasoning.
"""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from mcma.app.browser_supervisor import BrowserSupervisor
from mcma.app.connection_state import ConnectionStateTracker
from mcma.app.composition import build_app, build_tls_config, make_session_observer
from mcma.app.provisioning import ensure_canonical_accounts
from mcma.app.serve import TlsConfig, build_ssl_context, serve
from mcma.core.central_config import CentralConfigurationError, load_central_settings, validate_central_settings
from mcma.core.config import Settings
from mcma.core.aead import key_file_permission_problem, load_key_file
from mcma.core.mutex import create_single_instance_mutex
from mcma.execution.inputs import AesGcmInputEncryptor
from mcma.notifications.service import NotificationService
from mcma.persistence.db import open_database
from mcma.portal.vault import AesGcmSessionVaultBackend, PosixVaultDirectoryVerifier

logger = logging.getLogger(__name__)


@dataclass
class CentralServer:
    """Everything the central composition owns. `close()` is idempotent."""

    settings: Settings
    app: Any
    tls_config: TlsConfig
    notification_service: NotificationService
    api_conn: Any
    _resources: list = field(default_factory=list)
    _closed: bool = False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for release in reversed(self._resources):
            try:
                release()
            except Exception:
                logger.info("a resource was already closed at shutdown", exc_info=True)


def _verify_filesystem(settings: Settings) -> None:
    """Checks that need the real filesystem, run BEFORE the database is
    opened, the lock taken or anything served. Reports every problem."""
    problems: list[str] = []

    if not Path(settings.db_path).parent.is_dir():
        problems.append(f"the directory for db_path does not exist: {Path(settings.db_path).parent}")

    vault = Path(settings.vault_dir)
    if not vault.is_dir():
        problems.append(f"vault_dir must already exist and be a directory: {vault}")
    elif os.name == "posix" and not PosixVaultDirectoryVerifier().verify_restrictive(vault):
        problems.append(
            "vault_dir must be a real directory (not a symlink) owned by the service user "
            f"with mode 0700 or stricter: {vault}"
        )

    # The TLS private key is confidential. It must exist and, on POSIX,
    # belong to the service user with no group/other access.
    tls_key = Path(settings.tls_key_path)
    if not tls_key.is_file():
        problems.append(f"tls_key_path does not exist or is not a file: {tls_key}")
    elif os.name == "posix":
        info = os.stat(tls_key)
        problem = key_file_permission_problem(info.st_mode, info.st_uid, os.geteuid())
        if problem is not None:
            problems.append(f"tls_key_path: {problem}")

    # Two names for one file: a hard link survives path resolution.
    first, second = Path(settings.session_vault_key_path), Path(settings.job_input_key_path)
    try:
        if first.exists() and second.exists() and os.path.samefile(first, second):
            problems.append("session_vault_key_path and job_input_key_path refer to the same file")
    except OSError:
        problems.append("the key files could not be compared")

    if problems:
        raise CentralConfigurationError(problems)


class _Lifecycle:
    shutting_down = False


def create_central_server(
    settings: Settings,
    *,
    notification_browser_launcher: Optional[Callable[[], Any]] = None,
    _test_only_portable_mutex: bool = False,
) -> CentralServer:
    """Steps 1 and 3-6 (TLS is checked by run_central_server, which is the
    only caller that serves). Returns without serving, so it is testable;
    on failure everything already acquired is released."""
    validate_central_settings(settings)

    _verify_filesystem(settings)

    resources: list = []
    try:
        mutex = create_single_instance_mutex(
            settings.mutex_name,
            _test_only_portable_backend=_test_only_portable_mutex,
            lock_path=settings.instance_lock_path,
        )
        mutex.acquire()
        resources.append(mutex.release)

        # Each key file is read ONCE, here, and the resulting objects serve
        # the whole process: the poller, manual refresh and job-input
        # encryption never re-read a file per request.
        session_key = load_key_file(settings.session_vault_key_path)
        input_key = load_key_file(settings.job_input_key_path)
        if hmac.compare_digest(session_key, input_key):
            raise CentralConfigurationError(
                ["the session vault key and the job input key must not be identical key material"]
            )
        crypto_backend = AesGcmSessionVaultBackend(session_key)
        encryptor = AesGcmInputEncryptor(input_key)
        del session_key, input_key

        api_conn = open_database(Path(settings.db_path))
        resources.append(api_conn.close)
        ensure_canonical_accounts(api_conn)
        # Its own connection, like the local runner's: the API's sync
        # endpoints run on worker threads while the poller runs on the
        # event loop (see mcma.app.main's "TWO CONNECTIONS" note).
        poller_conn = open_database(Path(settings.db_path))
        resources.append(poller_conn.close)

        tracker = ConnectionStateTracker()
        supervisor = BrowserSupervisor()
        service = NotificationService(
            poller_conn, settings,
            crypto_backend=crypto_backend,
            session_observer=make_session_observer(tracker),
            browser_launcher=notification_browser_launcher,
            on_browser_ready=supervisor.mark_notification_ready,
            on_browser_lost=supervisor.mark_notification_lost,
        )
        lifecycle = _Lifecycle()

        @contextlib.asynccontextmanager
        async def _lifespan(_app):
            task = asyncio.create_task(service.run(settings.poll_interval_seconds))
            try:
                yield
            finally:
                lifecycle.shutting_down = True
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
                await service.stop()
                server.close()

        app = build_app(
            api_conn, settings, encryptor,
            lifespan=_lifespan, supervisor=supervisor, connection_tracker=tracker,
            expose_loopback_apps=False,
            portal_login_enabled=False,
            crypto_backend=crypto_backend,
            # Phase 1C-B central-integration correction: DRY_RUN creation
            # is now enabled -- the workstation runner registry, dispatch
            # and the server-owned DRY_RUN lifecycle (claim/start/finish)
            # are all wired, so a DRY_RUN queued here can genuinely be
            # picked up and completed by a workstation. EXECUTE creation
            # stays refused with RUNNER_CONTROL_PLANE_UNAVAILABLE before
            # anything is stored: EXECUTE dispatch/form-filling is not a
            # sanctioned central capability yet (INC-00's baseline writer
            # stays permanently disabled; the future VerifiedMissionWriter
            # is the only sanctioned path, and it does not exist here).
            # Neither flag is a client-visible setting -- both are fixed at
            # composition time by this module alone.
            dry_run_creation_available=True,
            execute_creation_available=False,
            # Runner registry (enrollment, identity, heartbeat, readiness,
            # revocation): DB rows and HTTP only. No browser, no background
            # thread -- online/offline is derived from server time on read.
            runner_registry_enabled=True,
            server_state_provider=lambda: {
                "notifications": service.state.value,
                "shutting_down": lifecycle.shutting_down,
            },
        )
        server = CentralServer(
            settings=settings, app=app, tls_config=build_tls_config(settings),
            notification_service=service, api_conn=api_conn, _resources=resources,
        )
        return server
    except BaseException:
        for release in reversed(resources):
            with contextlib.suppress(Exception):
                release()
        raise


def run_central_server(settings: Settings) -> None:  # pragma: no cover - real server loop
    validate_central_settings(settings)
    tls_config = build_tls_config(settings)
    build_ssl_context(tls_config)  # fail closed on a bad certificate BEFORE anything opens
    server = create_central_server(settings)
    try:
        serve(server.app, tls_config)
    finally:
        server.close()


def main() -> None:  # pragma: no cover - entry point
    """`python -m mcma.app.central_server` -- configuration comes from the
    file named by MCMA_CONFIG_FILE plus MCMA_* overrides; there are no
    defaults to fall back on."""
    try:
        settings = load_central_settings()
    except CentralConfigurationError as exc:
        raise SystemExit(f"refusing to start: {exc}") from None
    run_central_server(settings)


if __name__ == "__main__":  # pragma: no cover
    main()
