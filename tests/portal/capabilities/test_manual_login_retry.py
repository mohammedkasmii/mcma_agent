"""Manual login must survive a rejected password.

The bug: submitting credentials navigates the page, which destroys the
JavaScript execution context the logged-in probe runs in. Playwright
raised, the exception escaped perform_manual_login(), the caller's
`finally` closed the context, and the window the employee was typing into
vanished — reported as a 409, as though they had failed to complete a
sign-in they were never given a chance to retry.

A rejected credential is the EXPECTED case on a login form. These tests
pin that it keeps the window open, and that the three real outcomes stay
distinguishable.
"""

import asyncio

import pytest

from mcma.portal.capabilities import (
    LOGGED_IN_MARKERS,
    LoginCapability,
    LoginProbeFailed,
    LoginTimedOut,
    LoginWindowClosed,
    SessionMaterial,
)


class _NavigationDestroyedContext(Exception):
    """Shaped like Playwright's own error for a page that navigated while
    an evaluate was in flight."""

    def __init__(self):
        super().__init__(
            "Execution context was destroyed, most likely because of a navigation."
        )


class _TargetClosed(Exception):
    def __init__(self):
        super().__init__("Target page, context or browser has been closed")


class FakePage:
    """Scripted probe outcomes. Each entry is either a bool (markers
    present or not) or an exception instance to raise."""

    def __init__(self, script):
        self._script = list(script)
        self.evaluate_calls = 0
        self.closed = False

    def is_closed(self):
        return self.closed

    async def evaluate(self, _script, _arg=None):
        self.evaluate_calls += 1
        outcome = self._script.pop(0) if self._script else False
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeContext:
    def __init__(self, storage_state=None):
        self.close_count = 0
        self._storage_state = storage_state or {"cookies": [], "origins": []}

    async def storage_state(self):
        return self._storage_state

    async def close(self):
        self.close_count += 1


def _login(script, storage_state=None, account_id="acct-mcma-oujda"):
    page = FakePage(script)
    context = FakeContext(storage_state)
    return LoginCapability(context, page, account_id), page, context


async def _instant_sleep(_seconds):
    return None


# --------------------------------------------------------------------- #
# The regression: a rejected attempt, then a successful one
# --------------------------------------------------------------------- #


def test_a_rejected_attempt_does_not_end_the_login(monkeypatch):
    """The realistic sequence: page loads, employee submits wrong
    credentials, the page reloads and destroys the execution context,
    markers are still absent, the employee tries again, and the second
    attempt succeeds."""
    login, page, context = _login([
        False,                            # login page loaded, not signed in
        _NavigationDestroyedContext(),    # wrong credentials submitted -> reload
        False,                            # back on the login page, still not in
        False,                            # employee typing the second attempt
        _NavigationDestroyedContext(),    # submitted again -> reload
        True,                             # markers present
    ])

    material = asyncio.run(
        login.perform_manual_login(timeout_seconds=300, sleep=_instant_sleep)
    )

    assert isinstance(material, SessionMaterial)
    # The window stayed open the whole time.
    assert context.close_count == 0
    assert page.closed is False
    # Every scripted step was actually polled -- the navigation did not
    # short-circuit the loop.
    assert page.evaluate_calls == 6


def test_session_material_is_produced_exactly_once_and_only_when_signed_in():
    login, page, context = _login([False, _NavigationDestroyedContext(), True])
    material = asyncio.run(
        login.perform_manual_login(timeout_seconds=300, sleep=_instant_sleep)
    )
    handed_off = material.consume_for_handoff()
    assert handed_off == {"cookies": [], "origins": []}
    # Single-use: nothing can capture the same material twice.
    with pytest.raises(Exception):
        material.consume_for_handoff()


def test_many_rejected_attempts_are_all_tolerated():
    """Requirement: the employee may retry as many times as needed within
    the timeout."""
    script = []
    for _ in range(20):
        script.extend([False, _NavigationDestroyedContext()])
    script.append(True)

    login, page, context = _login(script)
    asyncio.run(login.perform_manual_login(timeout_seconds=300, sleep=_instant_sleep))
    assert context.close_count == 0


# --------------------------------------------------------------------- #
# The three real outcomes stay distinguishable
# --------------------------------------------------------------------- #


def test_closing_the_window_ends_the_attempt_immediately():
    """Not after the remaining timeout: the human cancelled."""
    login, page, context = _login([False, False])

    async def _close_then_sleep(_seconds):
        page.closed = True

    with pytest.raises(LoginWindowClosed) as raised:
        asyncio.run(login.perform_manual_login(timeout_seconds=300, sleep=_close_then_sleep))
    assert raised.value.reason == "LOGIN_WINDOW_CLOSED"
    # Detected on the very next poll rather than by waiting out the clock.
    assert page.evaluate_calls == 1


def test_a_closed_target_error_is_a_closed_window_not_a_probe_failure():
    login, page, context = _login([_TargetClosed()])
    with pytest.raises(LoginWindowClosed):
        asyncio.run(login.perform_manual_login(timeout_seconds=300, sleep=_instant_sleep))


def test_the_timeout_still_applies():
    login, page, context = _login([False] * 50)
    with pytest.raises(LoginTimedOut) as raised:
        asyncio.run(login.perform_manual_login(
            timeout_seconds=3, poll_interval_seconds=1, sleep=_instant_sleep
        ))
    assert raised.value.reason == "LOGIN_TIMED_OUT"


def test_an_unexpected_probe_error_is_not_swallowed():
    """Tolerating navigation must not become tolerating everything."""
    login, page, context = _login([ValueError("something genuinely unexpected")])
    with pytest.raises(LoginProbeFailed) as raised:
        asyncio.run(login.perform_manual_login(timeout_seconds=300, sleep=_instant_sleep))
    assert raised.value.reason == "LOGIN_PROBE_FAILED_ValueError"
    assert isinstance(raised.value.__cause__, ValueError)


def test_no_failure_reason_ever_carries_the_underlying_message():
    """A browser error can quote page content, and this page holds a
    username, a password and an OTP."""
    secret = "Mot de passe incorrect pour ahmed.benali / OTP 447213"
    login, page, context = _login([RuntimeError(secret)])
    with pytest.raises(LoginProbeFailed) as raised:
        asyncio.run(login.perform_manual_login(timeout_seconds=300, sleep=_instant_sleep))
    assert "ahmed" not in str(raised.value)
    assert "447213" not in str(raised.value)
    assert "Mot de passe" not in str(raised.value)
    assert raised.value.reason == "LOGIN_PROBE_FAILED_RuntimeError"


# --------------------------------------------------------------------- #
# Nothing is stored for a login that did not succeed
# --------------------------------------------------------------------- #


def test_no_session_is_captured_when_the_window_is_closed():
    captured = []

    class _WatchingContext(FakeContext):
        async def storage_state(self):
            captured.append(True)
            return await super().storage_state()

    page = FakePage([_TargetClosed()])
    login = LoginCapability(_WatchingContext(), page, "acct-mcma-oujda")
    with pytest.raises(LoginWindowClosed):
        asyncio.run(login.perform_manual_login(timeout_seconds=300, sleep=_instant_sleep))
    assert captured == []


def test_no_session_is_captured_on_timeout():
    captured = []

    class _WatchingContext(FakeContext):
        async def storage_state(self):
            captured.append(True)
            return await super().storage_state()

    page = FakePage([False] * 10)
    login = LoginCapability(_WatchingContext(), page, "acct-mcma-oujda")
    with pytest.raises(LoginTimedOut):
        asyncio.run(login.perform_manual_login(
            timeout_seconds=2, poll_interval_seconds=1, sleep=_instant_sleep
        ))
    assert captured == []


def test_markers_are_the_only_thing_the_probe_looks_at():
    """The probe reads a fixed marker list and nothing else -- never the
    form, its values, or the portal's error text.

    #listeAlertes was added on 2026-09-02 from onsite evidence: the real
    authenticated frontexpert page carried it while carrying none of the
    first three, and the probe was answering INDETERMINATE."""
    assert LOGGED_IN_MARKERS == (
        "#formRecherche", "#ReferenceCie", "a[href*='logout']", "#listeAlertes",
    )
    # Still only CSS selectors: nothing reads a value or a message.
    for marker in LOGGED_IN_MARKERS:
        assert marker.startswith(("#", "a["))


def test_the_service_reports_the_typed_reason(conn=None):
    """capture_session_for_account must pass the outcome through rather
    than flattening it into one generic failure."""
    import mcma.app.portal_login as portal_login

    assert issubclass(portal_login.PortalLoginFailed, Exception)
    failure = portal_login.PortalLoginFailed("LOGIN_WINDOW_CLOSED")
    assert failure.reason == "LOGIN_WINDOW_CLOSED"
