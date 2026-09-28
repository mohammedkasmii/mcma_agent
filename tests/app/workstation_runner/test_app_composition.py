"""Phase 1B-B composition-root wiring: proves app.py binds the REAL,
reviewed browser-session objects/functions -- not a typo'd duplicate, and
never accidentally the SAME backend selector as the unrelated runner
identity file -- without ever constructing a live GUI, performing real
DPAPI I/O, or opening a network client. _run_with_mutex_held() itself
builds a real tk.Tk() and calls mainloop(), which this file deliberately
never invokes (see conftest.py's docstring on why creating an extra,
independent Tk() interpreter in this test suite is unsafe); module-level
name identity is enough to prove the wiring is correct."""

from mcma.app.workstation_runner import app as app_module
from mcma.app.workstation_runner.browser_worker import BrowserSessionWorker
from mcma.app.workstation_runner.identity import select_production_crypto_backend as select_identity_backend
from mcma.app.workstation_runner.session_store import WorkstationSessionStore
from mcma.app.workstation_runner.session_store import (
    select_production_crypto_backend as select_session_backend,
)
from mcma.app.workstation_runner.sessions import VerificationScheduler, WorkstationSessionManager
from mcma.portal.workstation_sessions import perform_manual_login, verify_saved_session


def test_app_imports_the_real_reviewed_portal_functions_unchanged():
    assert app_module.perform_manual_login is perform_manual_login
    assert app_module.verify_saved_session is verify_saved_session


def test_app_uses_a_session_specific_dpapi_backend_selector_never_the_identity_one():
    """Regression guard: the session store and the runner identity file
    must never share a crypto-backend SELECTOR reference by accident --
    each is its own independently reviewed CURRENT_USER backend, over a
    completely different secret (see session_store.py's own docstring)."""
    assert app_module.select_session_crypto_backend is select_session_backend
    assert app_module.select_session_crypto_backend is not select_identity_backend
    assert app_module.select_production_crypto_backend is select_identity_backend


def test_app_imports_the_real_browser_session_types():
    assert app_module.WorkstationSessionStore is WorkstationSessionStore
    assert app_module.WorkstationSessionManager is WorkstationSessionManager
    assert app_module.BrowserSessionWorker is BrowserSessionWorker
    assert app_module.VerificationScheduler is VerificationScheduler


def test_app_uses_the_production_identity_read_contracts_never_pilot_contracts_for_dry_run():
    """Phase 1C-B release-blocker correction: the DRY_RUN identity gate's
    read contracts must come from mcma.portal.sinauto_contracts (the
    production module), never mcma.portal.pilot_contracts."""
    from mcma.portal.sinauto_contracts import identity_read_contracts

    assert app_module.identity_read_contracts is identity_read_contracts
    assert not hasattr(app_module, "pilot_read_contracts")


def test_app_uses_pilot_write_contracts_only_at_an_explicit_loopback_host_for_execute():
    """Phase 1C-C Pass 2A, requirement G: mcma.portal.sinauto_contracts
    deliberately has no write_contracts() at all (no reviewed production
    row-op contract exists pending G5) -- the ONLY legally-usable write
    contracts today are the pilot/loopback ones, wired here at an
    EXPLICIT loopback host, never the production sinauto host, and never
    a client-settable value. writer.py's own _require_loopback_host is
    the structural backstop regardless of this wiring."""
    import ipaddress
    from urllib.parse import urlsplit

    from mcma.portal.pilot_contracts import DEFAULT_PILOT_HOST, pilot_allowed_host
    from mcma.portal.pilot_contracts import write_contracts as pilot_write_contracts
    from mcma.portal.sinauto_contracts import DEFAULT_SINAUTO_HOST

    assert app_module.DEFAULT_PILOT_HOST is DEFAULT_PILOT_HOST
    assert app_module.pilot_allowed_host is pilot_allowed_host
    assert app_module.pilot_write_contracts is pilot_write_contracts
    # The two host constants are never accidentally swapped.
    assert DEFAULT_PILOT_HOST != DEFAULT_SINAUTO_HOST
    hostname = urlsplit(f"http://{DEFAULT_PILOT_HOST}").hostname
    assert ipaddress.ip_address(hostname).is_loopback


def test_dry_run_identity_check_wires_dynamic_mission_authorization():
    import inspect

    from mcma.portal.workstation_sessions import perform_dry_run_identity_check

    assert app_module.perform_dry_run_identity_check is perform_dry_run_identity_check
    source = inspect.getsource(perform_dry_run_identity_check)
    assert "dynamic_mission_authorization=True" in source
