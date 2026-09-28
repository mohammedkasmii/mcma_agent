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
