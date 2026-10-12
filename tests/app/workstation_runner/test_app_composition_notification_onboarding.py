"""Composition-root wiring of notification onboarding (name identity + an AST
read of _run_with_mutex_held, since the real function builds Tk and a
mainloop that the suite must never run -- see test_app_composition.py)."""

import ast
import inspect

from mcma.app.workstation_runner import app as app_module
from mcma.app.workstation_runner import notification_login
from mcma.app.workstation_runner.browser_gate import BrowserOperationGate
from mcma.app.workstation_runner.notification_onboarding import NotificationOnboardingLifecycle


def _calls(name: str) -> list:
    tree = ast.parse(inspect.getsource(app_module._run_with_mutex_held).replace("\r", ""))
    return [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == name
    ]


def _kw(call: ast.Call) -> dict:
    return {kw.arg: ast.unparse(kw.value) for kw in call.keywords}


def test_app_binds_the_real_notification_login_and_lifecycle_types():
    assert app_module.perform_notification_login is notification_login.perform_notification_login
    assert app_module.NotificationOnboardingLifecycle is NotificationOnboardingLifecycle
    assert app_module.BrowserOperationGate is BrowserOperationGate


def test_one_shared_gate_is_given_to_every_browser_owner():
    assert len(_calls("BrowserOperationGate")) == 1
    for owner in ("BrowserSessionWorker", "JobPollingLifecycle", "NotificationOnboardingLifecycle", "RunnerController"):
        calls = _calls(owner)
        assert len(calls) == 1, owner
        assert _kw(calls[0]).get("gate") == "browser_gate", owner


def test_onboarding_lifecycle_gets_the_notification_login_and_never_the_session_store():
    (call,) = _calls("NotificationOnboardingLifecycle")
    assert ast.unparse(call.args[1]) == "perform_notification_login"
    assert "session_store" not in ast.unparse(call)


def test_controller_receives_an_onboarding_factory():
    (call,) = _calls("RunnerController")
    assert "onboarding_lifecycle_factory" in _kw(call)


def test_runner_account_ids_and_heartbeat_readiness_are_untouched_by_onboarding():
    from mcma.app.workstation_runner.protocol import NOTIFICATION_ONBOARDING_ACCOUNT_IDS, RUNNER_ACCOUNT_IDS

    assert RUNNER_ACCOUNT_IDS == ("acct-mcma-oujda", "acct-mcma-nador")
    assert set(NOTIFICATION_ONBOARDING_ACCOUNT_IDS) - set(RUNNER_ACCOUNT_IDS) == {"acct-mamda-oujda", "acct-mamda-nador"}
