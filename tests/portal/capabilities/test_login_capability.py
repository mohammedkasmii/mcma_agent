"""
INC-08 -- LoginCapability: narrow onboarding-only behavior (amendment #6),
lifecycle enforcement (amendment #5), and no lease involvement (amendment #2
-- login is synthetic/onboarding-only, it cannot store or replace a session).
"""

import inspect

import pytest

from capabilities_test_support import (
    ALLOWED_HOST,
    AUTH_LOGIN_CONTRACT,
    FailingNewPageContext,
    FakeBrowser,
    FakePage,
    ROGUE_FINAL_LABELED_AUTH_CONTRACT,
    READ_LIST_MISSIONS_CONTRACT,
    run_async,
)
from mcma.portal.capabilities import (
    LoginCapability,
    LoginTimedOut,
    SessionMaterial,
    open_login_session,
)


async def _fast_sleep(_seconds):
    return None


# --------------------------------------------------------------------- #
# Contract-scope enforcement (before any context is created)
# --------------------------------------------------------------------- #


def test_open_login_session_rejects_non_auth_contract():
    browser = FakeBrowser()
    with pytest.raises(ValueError):
        run_async(
            open_login_session(browser, "acct-1", (READ_LIST_MISSIONS_CONTRACT,), ALLOWED_HOST)
        )
    assert browser.new_context_calls == []


def test_open_login_session_rejects_row_write_contract():
    from capabilities_test_support import ROGUE_ROW_WRITE_CONTRACT

    browser = FakeBrowser()
    with pytest.raises(ValueError):
        run_async(open_login_session(browser, "acct-1", (ROGUE_ROW_WRITE_CONTRACT,), ALLOWED_HOST))
    assert browser.new_context_calls == []


def test_open_login_session_rejects_permanently_blocked_route_even_if_labeled_auth():
    browser = FakeBrowser()
    with pytest.raises(ValueError):
        run_async(
            open_login_session(
                browser, "acct-1", (ROGUE_FINAL_LABELED_AUTH_CONTRACT,), ALLOWED_HOST
            )
        )
    assert browser.new_context_calls == []


# --------------------------------------------------------------------- #
# Account-id validation
# --------------------------------------------------------------------- #


@pytest.mark.parametrize("bad_account_id", ["", "   ", None, 42])
def test_open_login_session_rejects_empty_or_non_string_account_id(bad_account_id):
    browser = FakeBrowser()
    with pytest.raises(ValueError):
        run_async(open_login_session(browser, bad_account_id, (AUTH_LOGIN_CONTRACT,), ALLOWED_HOST))
    assert browser.new_context_calls == []


# --------------------------------------------------------------------- #
# Fixed navigation only; context setup failure closes and fails closed
# --------------------------------------------------------------------- #


def test_open_login_session_navigates_only_to_its_fixed_login_route():
    browser = FakeBrowser()
    login = run_async(open_login_session(browser, "acct-1", (AUTH_LOGIN_CONTRACT,), ALLOWED_HOST))
    page = browser.contexts_created[0].pages_created[0]
    assert page.goto_calls == [f"http://{ALLOWED_HOST}/SinAuto_MCMA/login"]
    run_async(login.close())


def test_open_login_session_closes_context_when_new_page_fails():
    browser = FakeBrowser(context_factory=FailingNewPageContext)
    with pytest.raises(RuntimeError):
        run_async(open_login_session(browser, "acct-1", (AUTH_LOGIN_CONTRACT,), ALLOWED_HOST))
    assert browser.contexts_created[0].closed_count == 1


# --------------------------------------------------------------------- #
# perform_manual_login: validation, polling, timeout, no partial material
# --------------------------------------------------------------------- #


class _StorageStateContext:
    def __init__(self, state=None):
        self.state = state or {"cookies": [], "origins": []}

    async def storage_state(self):
        return self.state

    async def close(self, **kwargs):
        pass


def test_perform_manual_login_returns_session_material_once_markers_appear():
    page = FakePage(evaluate_results=[False, False, True])
    capability = LoginCapability(_StorageStateContext(), page, "acct-1")
    material = run_async(
        capability.perform_manual_login(poll_interval_seconds=0.001, timeout_seconds=1, sleep=_fast_sleep)
    )
    assert isinstance(material, SessionMaterial)


def test_perform_manual_login_times_out_and_returns_no_partial_material():
    page = FakePage(evaluate_results=[False, False, False, False, False])
    capability = LoginCapability(_StorageStateContext(), page, "acct-1")
    with pytest.raises(LoginTimedOut):
        run_async(
            capability.perform_manual_login(
                poll_interval_seconds=0.001, timeout_seconds=0.002, sleep=_fast_sleep
            )
        )


@pytest.mark.parametrize("bad_value", [0, -1, float("inf"), float("nan"), "1", None])
def test_perform_manual_login_rejects_non_positive_or_non_finite_poll_interval(bad_value):
    page = FakePage()
    capability = LoginCapability(_StorageStateContext(), page, "acct-1")
    with pytest.raises(ValueError):
        run_async(capability.perform_manual_login(poll_interval_seconds=bad_value, timeout_seconds=1))
    assert page.evaluate_calls == []


@pytest.mark.parametrize("bad_value", [0, -1, float("inf"), float("nan"), "1", None])
def test_perform_manual_login_rejects_non_positive_or_non_finite_timeout(bad_value):
    page = FakePage()
    capability = LoginCapability(_StorageStateContext(), page, "acct-1")
    with pytest.raises(ValueError):
        run_async(capability.perform_manual_login(poll_interval_seconds=1, timeout_seconds=bad_value))
    assert page.evaluate_calls == []


# --------------------------------------------------------------------- #
# Lifecycle: fail after close, without touching the page; idempotent close
# --------------------------------------------------------------------- #


def test_methods_fail_after_close_without_touching_the_page():
    page = FakePage(evaluate_results=[True])
    capability = LoginCapability(_CountingCloseContext(), page, "acct-1")
    run_async(capability.close())
    with pytest.raises(RuntimeError):
        run_async(capability.perform_manual_login(poll_interval_seconds=0.001, timeout_seconds=0.01))
    assert page.evaluate_calls == []


def test_close_is_idempotent():
    context = _CountingCloseContext()
    capability = LoginCapability(context, FakePage(), "acct-1")
    run_async(capability.close())
    run_async(capability.close())
    assert context.closed_count == 1


class _CountingCloseContext:
    def __init__(self):
        self.closed_count = 0

    async def close(self, **kwargs):
        self.closed_count += 1


# --------------------------------------------------------------------- #
# Public surface + narrow behavior (amendment #6)
# --------------------------------------------------------------------- #


def test_public_surface_is_exactly_perform_manual_login_and_close():
    public = {
        name
        for name in dir(LoginCapability)
        if not name.startswith("_") and callable(getattr(LoginCapability, name))
    }
    assert public == {"perform_manual_login", "close"}


def test_no_page_context_evaluate_or_request_exposed():
    public_instance_attrs = {n for n in dir(LoginCapability) if not n.startswith("_")}
    assert "page" not in public_instance_attrs
    assert "context" not in public_instance_attrs
    assert "evaluate" not in public_instance_attrs
    assert "request" not in public_instance_attrs


def test_perform_manual_login_accepts_no_credential_arguments():
    signature = inspect.signature(LoginCapability.perform_manual_login)
    param_names = set(signature.parameters) - {"self"}
    assert param_names == {"poll_interval_seconds", "timeout_seconds", "sleep"}


def test_login_capability_source_never_references_row_or_final_endpoints():
    source = inspect.getsource(LoginCapability)
    forbidden = (
        "createRapportDefDet",
        "updateDevisDet",
        "garageModifierValDevis",
        "validerDevis",
        "expertCloturerMission",
        "cloturerMission",
        "enregistrerMission",
        "ajouterDocument",
        "deleteDocument",
        "cloturerTraitement",
        "deleteDevisDet",
        "gestionexpert/index",
    )
    for token in forbidden:
        assert token not in source, token
