"""
mcma.app.composition -- the assembly helpers SHARED by the local Windows
composition (mcma.app.main) and the central server composition
(mcma.app.central_server).

This module exists so that the central server can build its app without
importing mcma.app.main, which drags in the local job runner, the writer,
the pilot contracts and ActiveReviewRegistry. Nothing here may import
mcma.execution.runner, mcma.portal.writer, mcma.portal.pilot_contracts or
mcma.execution.browser_handoff; tests/central/test_central_import_isolation.py
proves it in a fresh interpreter.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

from mcma.app.api.app import create_api_app
from mcma.app.auth.bootstrap import create_bootstrap_app
from mcma.app.auth.provider import LocalUserAuthProvider
from mcma.app.connection_state import ConnectionStateTracker
from mcma.app.frontend import mount_frontend
from mcma.app.onboarding import create_onboarding_app
from mcma.app.portal_login import capture_session_for_account
from mcma.app.provisioning import ensure_local_employee
from mcma.app.serve import TlsConfig
from mcma.core.config import Settings
from mcma.execution.inputs import InputEncryptor, get_input_encryptor
from mcma.execution.lease import acquire_account_lease
from mcma.notifications.poller import poll_one_account
from mcma.persistence.repositories.accounts import AccountsRepository
from mcma.portal.vault import CryptoBackend, get_acl_verifier, get_crypto_backend


def _is_loopback(host: str) -> bool:
    from ipaddress import ip_address

    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


def build_encryptor(settings: Settings) -> InputEncryptor:
    """Real DPAPI encryption unless a test explicitly asks otherwise.

    Selection is driven by allow_test_plaintext_job_inputs, NOT by
    dev_mode. Tying it to dev_mode meant the normal employee application
    -- which runs in the local/dev composition -- stored every dossier's
    JSON verbatim. Pointing at the mock portal and storing PII in the
    clear are unrelated decisions and are now unrelated settings."""
    return get_input_encryptor(
        _test_only_plaintext_backend=settings.allow_test_plaintext_job_inputs,
        key_path=settings.job_input_key_path,
    )


def build_session_backend(settings: Settings) -> CryptoBackend:
    """DPAPI on the Windows pilot; AES-256-GCM when a session vault key
    file is configured (central server); the test backend only on an
    explicit test opt-in. Never a silent fallback between them."""
    return get_crypto_backend(
        _test_only_in_memory_backend=settings.allow_test_only_session_vault,
        key_path=settings.session_vault_key_path,
    )


def make_session_observer(tracker: ConnectionStateTracker):
    """Turns an observed session state into a tracker update.

    Shared by the API's manual refresh and the background loop so both
    report the same way, and defined here rather than in the poller
    because mcma.notifications must not know about mcma.app.
    """

    def observe(account_id: str, state: str) -> None:
        if state == "AUTHENTICATED":
            tracker.mark_authenticated(account_id)
        elif state == "LOGGED_OUT":
            tracker.mark_logged_out(account_id)
        else:
            tracker.mark_unverified(account_id)

    return observe


def build_app(
    conn, settings: Settings, encryptor: InputEncryptor, *,
    lifespan=None, supervisor=None, connection_tracker=None,
    expose_loopback_apps: bool = True,
    portal_login_enabled: bool = True,
    server_state_provider=None,
    crypto_backend: "CryptoBackend | None" = None,
    agent_execution_available: bool = True,
    runner_registry_enabled: bool = False,
):
    """Assembles the one ASGI app: authenticated API + the built employee
    UI + the two loopback-only sub-apps. The sub-apps enforce their own loopback checks
    internally (mcma.app.auth.bootstrap._require_loopback,
    mcma.app.onboarding._require_loopback), so mounting them on the same
    LAN-served app does not expose them to the LAN.

    That in-app loopback check is sufficient only for a process reached
    directly. Behind a reverse proxy on the same host every proxied
    request arrives from 127.0.0.1, so the check would pass for the whole
    LAN. The central server therefore passes expose_loopback_apps=False:
    the sub-apps are not mounted at all rather than trusted to refuse.
    It likewise passes portal_login_enabled=False: an interactive login
    needs a visible browser, which a headless server does not have."""
    # What THIS process has observed about each portal session. Stored
    # ACTIVE material starts unverified: a fresh process has seen nothing,
    # and claiming CONNECTED from a database row is what left an account
    # signed in yesterday still offering "Actualiser" this morning.
    # Injected so the background poll loop -- which runs on its own
    # connection -- reports into the SAME tracker the API reads. Two
    # trackers would mean the loop's observations never reached /accounts.
    connection_tracker = connection_tracker or ConnectionStateTracker()

    # ONE session backend for the life of this app: the caller's, already
    # validated at startup, or -- only when none was supplied -- one built
    # here, once. Never re-resolved per request, so a key file is read at
    # startup and not again.
    if crypto_backend is None:
        crypto_backend = build_session_backend(settings)

    # The narrow observer handed to the poller: an account and an observed
    # state, nothing else -- no reader, no page, no session material.
    _observe_session_state = make_session_observer(connection_tracker)

    async def _open_portal_login(account_id: str) -> str:
        """Runs the login capture on the process's ONE browser -- the same
        one the runner uses -- so the window the employee signs into is a
        real, visible browser on their own machine."""
        # Raises BrowserNotReady / BrowserUnavailable, which the API
        # reports as themselves -- never as a failed portal login.
        browser = supervisor.get()
        session_id = await capture_session_for_account(
            conn, browser, account_id,
            instance_id=settings.instance_id,
            allowed_host=settings.portal_host,
            vault_dir=settings.vault_dir,
            crypto_backend=crypto_backend,
            acl_verifier=get_acl_verifier(),
        )
        # A completed login is positive evidence, not an assumption:
        # capture_session_for_account returns only after
        # perform_manual_login() has observed the logged-in markers; every
        # other outcome raises. So the employee sees "Connecté"
        # immediately rather than being told to verify what they just did.
        connection_tracker.mark_authenticated(account_id)
        return session_id

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

    async def _refresh_notifications(account_id: str) -> str:
        """The manual "Actualiser" path. Deliberately the SAME service the
        background loop uses -- a second scraper would be a second set of
        contracts, a second set of session-expiry rules, and two answers
        to the same question."""
        account = AccountsRepository(conn).get(account_id)
        if account is None:
            return "NO_SESSION"
        return await poll_one_account(
            # The headless browser: a manual refresh must not make a
            # window appear and vanish on the employee's screen.
            conn, supervisor.get_notification(), account_id, settings.notification_category_codes,
            instance_id=settings.instance_id,
            allowed_host=settings.portal_host,
            vault_dir=settings.vault_dir,
            crypto_backend=crypto_backend,
            entity=account.entity,
            session_observer=_observe_session_state,
        )

    app = create_api_app(
        conn,
        auth_provider=LocalUserAuthProvider(conn),
        encryptor=encryptor,
        secure_cookies=True,
        portal_login_opener=(
            _open_portal_login if supervisor is not None and portal_login_enabled else None
        ),
        local_user_id=local_user_id,
        notification_refresher=_refresh_notifications if supervisor is not None else None,
        connection_state_tracker=connection_tracker,
        server_state_provider=server_state_provider,
        agent_execution_available=agent_execution_available,
        runner_registry=runner_registry_enabled,
    )
    if lifespan is not None:
        app.router.lifespan_context = lifespan
    # Frontend V2, served from the same authenticated origin as the API.
    # Mounted AFTER create_api_app so every backend route is already
    # registered and keeps winning; the SPA routes are explicit, so a
    # mistyped API path stays a backend 404 rather than becoming HTML.
    mount_frontend(app)

    if expose_loopback_apps:
        _mount_loopback_apps(app, conn, settings, crypto_backend)
    # Reachable by the composition root so the runner can report into it.
    app.state.connection_tracker = connection_tracker
    return app


def _mount_loopback_apps(app, conn, settings: Settings, crypto_backend: CryptoBackend) -> None:
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
            backend=crypto_backend,
            acl_verifier=get_acl_verifier(),
            lease_provider=_lease_provider,
        ),
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
