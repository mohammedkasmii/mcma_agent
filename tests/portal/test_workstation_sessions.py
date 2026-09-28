"""mcma.portal.workstation_sessions -- Phase 1B-B Pass 2 adapter tests.

Deliberately self-contained fakes here rather than a bare cross-directory
import of tests/portal/capabilities/capabilities_test_support.py: that
module's own docstring documents why a same-purpose bare import across
test directories is unsafe in this suite (sys.modules collisions once the
whole suite runs together), and this file lives outside that package
anyway. A little duplication is the established trade-off.

No real Playwright browser is used anywhere in this file.
"""

from __future__ import annotations

import ast
import asyncio
import inspect
from contextlib import asynccontextmanager

import pytest

from mcma.portal import workstation_sessions
from mcma.portal.capabilities import (
    LoginProbeFailed, LoginTimedOut, LoginWindowClosed, SessionMaterial,
)
from mcma.portal.contracts import RouteContract
from mcma.portal.sinauto_contracts import DEFAULT_SINAUTO_HOST, category_discovery_contracts

OUJDA = "acct-mcma-oujda"
NADOR = "acct-mcma-nador"
MARKER = "SECRET-COOKIE-VALUE-MARKER-zzz"


def run_async(coro):
    return asyncio.run(coro)


def _storage_state(marker: str = MARKER) -> dict:
    return {
        "cookies": [{"name": "session", "value": marker, "domain": "sinauto.mamda-mcma.ma", "path": "/"}],
        "origins": [],
    }


# --------------------------------------------------------------------- #
# Fakes -- no real Playwright object anywhere
# --------------------------------------------------------------------- #


class FakePage:
    def __init__(self, evaluate_results=None, goto_exception=None, closed=False):
        self.goto_calls = []
        self.evaluate_calls = []
        self._evaluate_results = list(evaluate_results) if evaluate_results is not None else None
        self._goto_exception = goto_exception
        self._closed = closed

    def is_closed(self) -> bool:
        return self._closed

    async def goto(self, url, **kwargs):
        self.goto_calls.append(url)
        if self._goto_exception is not None:
            raise self._goto_exception

    async def evaluate(self, script, arg=None):
        self.evaluate_calls.append((script, arg))
        if self._evaluate_results is not None:
            if not self._evaluate_results:
                return None
            result = self._evaluate_results.pop(0)
            if isinstance(result, BaseException):
                raise result
            return result
        return None


class FakeContext:
    def __init__(
        self, *, page_factory=None, storage_state_result=None,
        new_page_exception=None, route_exception=None,
    ):
        self.route_calls = []
        self.ws_route_calls = []
        self.closed_count = 0
        self.pages_created = []
        self._page_factory = page_factory or (lambda: FakePage(evaluate_results=[True]))
        self._storage_state_result = (
            storage_state_result if storage_state_result is not None else {"cookies": [], "origins": []}
        )
        self._new_page_exception = new_page_exception
        self._route_exception = route_exception

    async def route(self, pattern, handler):
        if self._route_exception is not None:
            raise self._route_exception
        self.route_calls.append((pattern, handler))

    async def route_web_socket(self, pattern, handler):
        self.ws_route_calls.append((pattern, handler))

    async def new_page(self):
        if self._new_page_exception is not None:
            raise self._new_page_exception
        page = self._page_factory()
        self.pages_created.append(page)
        return page

    async def storage_state(self):
        return self._storage_state_result

    async def close(self, **kwargs):
        self.closed_count += 1


class FakeBrowser:
    def __init__(self, context_factory=None):
        self._context_factory = context_factory or FakeContext
        self.new_context_calls = []
        self.contexts_created = []

    async def new_context(self, **options):
        self.new_context_calls.append(options)
        context = self._context_factory()
        self.contexts_created.append(context)
        return context


def _browser(*, page_factory=None, storage_state_result=None, new_page_exception=None, route_exception=None):
    def factory():
        return FakeContext(
            page_factory=page_factory, storage_state_result=storage_state_result,
            new_page_exception=new_page_exception, route_exception=route_exception,
        )
    return FakeBrowser(context_factory=factory)


class LaunchBrowserRecorder:
    """Stands in for mcma.portal.browser.launch_browser -- records whether
    entry actually happened (headless=) and that the async context
    manager's own cleanup ran (closed_count), without touching real
    Playwright at all."""

    def __init__(self, browser):
        self.browser = browser
        self.headless_calls = []
        self.closed_count = 0

    def as_launch_browser(self):
        recorder = self

        @asynccontextmanager
        async def _fake_launch_browser(*, headless=False):
            recorder.headless_calls.append(headless)
            try:
                yield recorder.browser
            finally:
                recorder.closed_count += 1

        return _fake_launch_browser


def _patch_launch_browser(monkeypatch, browser):
    recorder = LaunchBrowserRecorder(browser)
    monkeypatch.setattr(workstation_sessions, "launch_browser", recorder.as_launch_browser())
    return recorder


# --------------------------------------------------------------------- #
# 1 & 2 -- account allowlist, fixed MCMA mapping, rejection before launch
# --------------------------------------------------------------------- #


@pytest.mark.parametrize("account_id", [OUJDA, NADOR])
def test_manual_login_navigates_to_the_fixed_mcma_login_route_for_both_accounts(monkeypatch, account_id):
    browser = _browser()
    _patch_launch_browser(monkeypatch, browser)
    material = run_async(workstation_sessions.perform_manual_login(account_id))
    page = browser.contexts_created[0].pages_created[0]
    assert page.goto_calls == [f"https://{DEFAULT_SINAUTO_HOST}/SinAuto_MCMA"]
    assert isinstance(material, SessionMaterial)


@pytest.mark.parametrize("account_id", [OUJDA, NADOR])
def test_verify_saved_session_navigates_to_the_fixed_mcma_search_page_for_both_accounts(monkeypatch, account_id):
    browser = _browser(page_factory=lambda: FakePage(evaluate_results=[{"logged_in": True, "logged_out": False}]))
    _patch_launch_browser(monkeypatch, browser)
    run_async(workstation_sessions.verify_saved_session(account_id, _storage_state()))
    page = browser.contexts_created[0].pages_created[0]
    assert page.goto_calls == [f"https://{DEFAULT_SINAUTO_HOST}/SinAuto_MCMA/expertise/frontexpert"]


@pytest.mark.parametrize("bad_account", ["acct-mamda-oujda", "acct-mcma-fes", "", None, 42])
def test_perform_manual_login_rejects_unknown_or_mamda_account_before_launch(monkeypatch, bad_account):
    browser = _browser()
    recorder = _patch_launch_browser(monkeypatch, browser)
    with pytest.raises(workstation_sessions.UnknownWorkstationAccount):
        run_async(workstation_sessions.perform_manual_login(bad_account))
    assert recorder.headless_calls == []
    assert browser.new_context_calls == []


@pytest.mark.parametrize("bad_account", ["acct-mamda-oujda", "acct-mcma-fes", "", None, 42])
def test_verify_saved_session_rejects_unknown_or_mamda_account_before_launch(monkeypatch, bad_account):
    browser = _browser()
    recorder = _patch_launch_browser(monkeypatch, browser)
    with pytest.raises(workstation_sessions.UnknownWorkstationAccount):
        run_async(workstation_sessions.verify_saved_session(bad_account, _storage_state()))
    assert recorder.headless_calls == []
    assert browser.new_context_calls == []


def test_verify_saved_session_uses_only_read_capability_contracts():
    contracts = category_discovery_contracts(DEFAULT_SINAUTO_HOST, "MCMA")
    assert all(c.capability == "read" for c in contracts)


# --------------------------------------------------------------------- #
# 3 & 4 -- headed manual login, headless verification
# --------------------------------------------------------------------- #


def test_manual_login_launches_headed(monkeypatch):
    browser = _browser()
    recorder = _patch_launch_browser(monkeypatch, browser)
    run_async(workstation_sessions.perform_manual_login(OUJDA))
    assert recorder.headless_calls == [False]


def test_verify_saved_session_launches_headless(monkeypatch):
    browser = _browser(page_factory=lambda: FakePage(evaluate_results=[{"logged_in": True, "logged_out": False}]))
    recorder = _patch_launch_browser(monkeypatch, browser)
    run_async(workstation_sessions.verify_saved_session(OUJDA, _storage_state()))
    assert recorder.headless_calls == [True]


# --------------------------------------------------------------------- #
# 5 -- no forbidden parameter anywhere on the public API
# --------------------------------------------------------------------- #


def test_perform_manual_login_signature_is_narrow():
    params = set(inspect.signature(workstation_sessions.perform_manual_login).parameters)
    assert params == {"account_id", "poll_interval_seconds", "timeout_seconds"}


def test_verify_saved_session_signature_is_narrow():
    params = set(inspect.signature(workstation_sessions.verify_saved_session).parameters)
    assert params == {"account_id", "storage_state"}


# --------------------------------------------------------------------- #
# 6 & 7 -- redacted SessionMaterial, cleanup after successful capture
# --------------------------------------------------------------------- #


def test_manual_login_returns_redacted_session_material(monkeypatch):
    browser = _browser(
        page_factory=lambda: FakePage(evaluate_results=[True]),
        storage_state_result=_storage_state(),
    )
    _patch_launch_browser(monkeypatch, browser)
    material = run_async(workstation_sessions.perform_manual_login(OUJDA))
    assert isinstance(material, SessionMaterial)
    assert material.account_id == OUJDA
    assert MARKER not in repr(material)
    assert MARKER not in str(material)


def test_successful_login_closes_capability_and_browser_after_capture(monkeypatch):
    browser = _browser()
    recorder = _patch_launch_browser(monkeypatch, browser)
    run_async(workstation_sessions.perform_manual_login(OUJDA))
    assert browser.contexts_created[0].closed_count == 1
    assert recorder.closed_count == 1


# --------------------------------------------------------------------- #
# 8 -- timeout / window-close / probe-failure cleanup
# --------------------------------------------------------------------- #


def test_login_timeout_closes_capability_and_browser(monkeypatch):
    browser = _browser(page_factory=lambda: FakePage(evaluate_results=[]))
    recorder = _patch_launch_browser(monkeypatch, browser)
    with pytest.raises(LoginTimedOut):
        run_async(
            workstation_sessions.perform_manual_login(
                OUJDA, poll_interval_seconds=0.001, timeout_seconds=0.005,
            )
        )
    assert browser.contexts_created[0].closed_count == 1
    assert recorder.closed_count == 1


def test_login_window_closed_by_employee_closes_capability_and_browser(monkeypatch):
    browser = _browser(page_factory=lambda: FakePage(closed=True))
    recorder = _patch_launch_browser(monkeypatch, browser)
    with pytest.raises(LoginWindowClosed):
        run_async(workstation_sessions.perform_manual_login(OUJDA))
    assert browser.contexts_created[0].closed_count == 1
    assert recorder.closed_count == 1


def test_login_probe_failure_closes_capability_and_browser(monkeypatch):
    browser = _browser(page_factory=lambda: FakePage(evaluate_results=[RuntimeError("boom")]))
    recorder = _patch_launch_browser(monkeypatch, browser)
    with pytest.raises(LoginProbeFailed):
        run_async(workstation_sessions.perform_manual_login(OUJDA))
    assert browser.contexts_created[0].closed_count == 1
    assert recorder.closed_count == 1


def test_verify_saved_session_navigation_failure_closes_context_and_browser(monkeypatch):
    browser = _browser(page_factory=lambda: FakePage(goto_exception=RuntimeError("boom")))
    recorder = _patch_launch_browser(monkeypatch, browser)
    with pytest.raises(workstation_sessions.SessionProbeFailed):
        run_async(workstation_sessions.verify_saved_session(OUJDA, _storage_state()))
    assert browser.contexts_created[0].closed_count == 1
    assert recorder.closed_count == 1


# --------------------------------------------------------------------- #
# 9 -- cancellation cleanup and CancelledError propagation
# --------------------------------------------------------------------- #


def test_manual_login_cancellation_cleans_up_and_propagates(monkeypatch):
    browser = _browser(page_factory=lambda: FakePage(evaluate_results=[asyncio.CancelledError()]))
    recorder = _patch_launch_browser(monkeypatch, browser)
    with pytest.raises(asyncio.CancelledError):
        run_async(workstation_sessions.perform_manual_login(OUJDA))
    assert browser.contexts_created[0].closed_count == 1
    assert recorder.closed_count == 1


def test_verify_saved_session_cancellation_during_setup_cleans_up_and_propagates(monkeypatch):
    browser = _browser(new_page_exception=asyncio.CancelledError())
    recorder = _patch_launch_browser(monkeypatch, browser)
    with pytest.raises(asyncio.CancelledError):
        run_async(workstation_sessions.verify_saved_session(OUJDA, _storage_state()))
    assert browser.contexts_created[0].closed_count == 1
    assert recorder.closed_count == 1


# --------------------------------------------------------------------- #
# 10 -- verification maps AUTHENTICATED / LOGGED_OUT / INDETERMINATE
# --------------------------------------------------------------------- #


@pytest.mark.parametrize("evaluate_result,expected", [
    ({"logged_in": True, "logged_out": False}, workstation_sessions.SessionProbeOutcome.AUTHENTICATED),
    ({"logged_in": False, "logged_out": True}, workstation_sessions.SessionProbeOutcome.LOGGED_OUT),
    ({"logged_in": False, "logged_out": False}, workstation_sessions.SessionProbeOutcome.INDETERMINATE),
    ({"logged_in": True, "logged_out": True}, workstation_sessions.SessionProbeOutcome.INDETERMINATE),
])
def test_verify_saved_session_maps_all_observed_states(monkeypatch, evaluate_result, expected):
    browser = _browser(page_factory=lambda: FakePage(evaluate_results=[evaluate_result]))
    _patch_launch_browser(monkeypatch, browser)
    outcome = run_async(workstation_sessions.verify_saved_session(OUJDA, _storage_state()))
    assert outcome is expected


# --------------------------------------------------------------------- #
# 10b -- Pass 2 correction: the shared session-state helper is called in
# STRICT mode here, so an evaluation exception is a probe FAILURE, never
# folded into INDETERMINATE (that stays ReadCapability's own, unchanged,
# non-strict behavior -- see tests/portal/capabilities/test_read_capability.py).
# --------------------------------------------------------------------- #


def test_verify_saved_session_maps_evaluation_exception_to_session_probe_failed(monkeypatch):
    browser = _browser(page_factory=lambda: FakePage(evaluate_results=[RuntimeError(f"leaked {MARKER}")]))
    recorder = _patch_launch_browser(monkeypatch, browser)
    with pytest.raises(workstation_sessions.SessionProbeFailed) as exc_info:
        run_async(workstation_sessions.verify_saved_session(OUJDA, _storage_state()))
    assert MARKER not in str(exc_info.value)
    assert MARKER not in repr(exc_info.value)
    assert exc_info.value.__cause__ is None
    assert browser.contexts_created[0].closed_count == 1
    assert recorder.closed_count == 1


def test_verify_saved_session_genuine_ambiguous_evaluation_is_still_indeterminate(monkeypatch):
    """A SUCCESSFULLY evaluated but ambiguous page (no exception at all)
    must remain a genuine INDETERMINATE reading, never conflated with a
    probe failure -- the same scenario as the parametrized case above,
    isolated here to make the distinction from the exception case explicit."""
    browser = _browser(page_factory=lambda: FakePage(evaluate_results=[{"logged_in": False, "logged_out": False}]))
    _patch_launch_browser(monkeypatch, browser)
    outcome = run_async(workstation_sessions.verify_saved_session(OUJDA, _storage_state()))
    assert outcome is workstation_sessions.SessionProbeOutcome.INDETERMINATE


def test_verify_saved_session_cancellation_during_evaluation_propagates_and_cleans_up(monkeypatch):
    browser = _browser(page_factory=lambda: FakePage(evaluate_results=[asyncio.CancelledError()]))
    recorder = _patch_launch_browser(monkeypatch, browser)
    with pytest.raises(asyncio.CancelledError):
        run_async(workstation_sessions.verify_saved_session(OUJDA, _storage_state()))
    assert browser.contexts_created[0].closed_count == 1
    assert recorder.closed_count == 1


# --------------------------------------------------------------------- #
# Pass 2 correction: the search-page contract-count invariant must fail
# closed (not `assert`, which python -O strips), before any browser launch
# --------------------------------------------------------------------- #


def _read_contract(route: str, operation_type: str) -> RouteContract:
    return RouteContract(
        host=DEFAULT_SINAUTO_HOST, route=route, method="GET", query_fields=frozenset(),
        content_type=None, body_fields=frozenset(), capability="read", operation_type=operation_type,
    )


def test_verify_saved_session_fails_closed_on_zero_search_page_contracts(monkeypatch):
    browser = _browser()
    recorder = _patch_launch_browser(monkeypatch, browser)
    monkeypatch.setattr(
        workstation_sessions, "category_discovery_contracts",
        lambda host, entity: (_read_contract("/x", "notification_categories"),),
    )
    with pytest.raises(workstation_sessions.SessionProbeFailed):
        run_async(workstation_sessions.verify_saved_session(OUJDA, _storage_state()))
    assert recorder.headless_calls == []
    assert browser.new_context_calls == []


def test_verify_saved_session_fails_closed_on_multiple_search_page_contracts(monkeypatch):
    browser = _browser()
    recorder = _patch_launch_browser(monkeypatch, browser)
    monkeypatch.setattr(
        workstation_sessions, "category_discovery_contracts",
        lambda host, entity: (
            _read_contract("/a", "search_page"),
            _read_contract("/b", "search_page"),
        ),
    )
    with pytest.raises(workstation_sessions.SessionProbeFailed):
        run_async(workstation_sessions.verify_saved_session(OUJDA, _storage_state()))
    assert recorder.headless_calls == []
    assert browser.new_context_calls == []


# --------------------------------------------------------------------- #
# 11 & 12 -- setup/navigation exceptions produce ONLY a safe typed error;
# a distinctive marker never appears in exception str/repr
# --------------------------------------------------------------------- #


def test_verify_saved_session_context_creation_failure_is_wrapped_safely(monkeypatch):
    browser = _browser(route_exception=RuntimeError(f"leaked page content {MARKER}"))
    _patch_launch_browser(monkeypatch, browser)
    with pytest.raises(workstation_sessions.SessionProbeFailed) as exc_info:
        run_async(workstation_sessions.verify_saved_session(OUJDA, _storage_state()))
    assert MARKER not in str(exc_info.value)
    assert MARKER not in repr(exc_info.value)
    assert exc_info.value.__cause__ is None


def test_verify_saved_session_navigation_failure_is_wrapped_safely(monkeypatch):
    browser = _browser(page_factory=lambda: FakePage(goto_exception=RuntimeError(f"leaked {MARKER}")))
    _patch_launch_browser(monkeypatch, browser)
    with pytest.raises(workstation_sessions.SessionProbeFailed) as exc_info:
        run_async(workstation_sessions.verify_saved_session(OUJDA, _storage_state()))
    assert MARKER not in str(exc_info.value)
    assert MARKER not in repr(exc_info.value)
    assert exc_info.value.__cause__ is None


def test_unknown_account_error_has_a_fixed_message_and_no_marker():
    bad_account = f"SECRET-{MARKER}"
    try:
        run_async(workstation_sessions.perform_manual_login(bad_account))
    except workstation_sessions.UnknownWorkstationAccount as exc:
        assert MARKER not in str(exc)
        assert MARKER not in repr(exc)
    else:
        pytest.fail("expected UnknownWorkstationAccount")


def test_invalid_storage_state_error_has_a_fixed_message_and_no_marker():
    try:
        run_async(workstation_sessions.verify_saved_session(OUJDA, f"not-a-dict-{MARKER}"))
    except workstation_sessions.InvalidWorkstationStorageState as exc:
        assert MARKER not in str(exc)
        assert MARKER not in repr(exc)
    else:
        pytest.fail("expected InvalidWorkstationStorageState")


# --------------------------------------------------------------------- #
# 13 -- storage_state applied only via in-memory context options
# --------------------------------------------------------------------- #


def test_verify_saved_session_applies_storage_state_only_via_in_memory_context_options(monkeypatch):
    state = _storage_state()
    browser = _browser(page_factory=lambda: FakePage(evaluate_results=[{"logged_in": True, "logged_out": False}]))
    _patch_launch_browser(monkeypatch, browser)
    run_async(workstation_sessions.verify_saved_session(OUJDA, state))
    options = browser.new_context_calls[0]
    assert options["storage_state"] is state
    assert isinstance(options["storage_state"], dict)


def test_module_source_never_writes_a_file():
    source = inspect.getsource(workstation_sessions)
    for forbidden in ("open(", ".write(", "with open"):
        assert forbidden not in source


# --------------------------------------------------------------------- #
# 14 -- no Page/BrowserContext/Browser ever escapes the public API
# --------------------------------------------------------------------- #


def test_source_never_returns_or_yields_a_raw_playwright_object():
    source = inspect.getsource(workstation_sessions)
    for forbidden in ("return context", "return page", "return browser", "yield context", "yield page"):
        assert forbidden not in source


def test_return_types_are_never_playwright_objects():
    import typing

    hints = typing.get_type_hints(workstation_sessions.perform_manual_login)
    assert hints.get("return") is SessionMaterial
    hints = typing.get_type_hints(workstation_sessions.verify_saved_session)
    assert hints.get("return") is workstation_sessions.SessionProbeOutcome


# --------------------------------------------------------------------- #
# 15 -- no writer/form-filling/persistence/sqlite/mcma.app dependency
# --------------------------------------------------------------------- #


def test_module_declares_no_forbidden_imports():
    source = inspect.getsource(workstation_sessions)
    tree = ast.parse(source)
    imported_modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)
    forbidden_prefixes = (
        "sqlite3", "mcma.app", "mcma.persistence", "mcma.portal.writer", "mcma.portal.vault",
    )
    for module_name in imported_modules:
        assert not any(
            module_name == prefix or module_name.startswith(prefix + ".") for prefix in forbidden_prefixes
        ), module_name
