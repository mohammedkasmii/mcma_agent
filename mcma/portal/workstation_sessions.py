"""mcma.portal.workstation_sessions -- narrow adapter for the two Windows
workstation MCMA portal accounts (Phase 1B-B Pass 2).

acct-mcma-oujda and acct-mcma-nador are the ONLY accounts this module will
ever touch, and both are entity MCMA -- MAMDA is notification-only and has
no workstation login path anywhere in this module (see
mcma.app.workstation_runner.protocol's docstring on the same duplication-
over-cross-layer-import choice: mcma.portal must never import mcma.app, so
the two-account allowlist is a fresh, small, independently-reviewed literal
here, not an import of the runner's copy).

This module is not wired into the runner yet -- Pass 2 is the adapter
alone. It owns every Playwright-touching line for this feature; the future
browser worker in mcma.app.workstation_runner will call these two async
functions and must never import playwright itself.

Two operations only, both async, neither wrapped in asyncio.run() (the
future caller owns the event loop and must be able to cancel an in-flight
call cleanly):

  * perform_manual_login(account_id) -- opens a HEADED browser so the
    employee can sign in and enter their OTP directly in the portal's own
    UI, and returns the existing redacted SessionMaterial once
    LoginCapability positively observes the logged-in markers. Credentials
    and OTP never pass through this module -- there is no parameter for
    them anywhere in this file.
  * verify_saved_session(account_id, storage_state) -- opens a HEADLESS
    browser with the given storage_state applied purely in memory (never
    written to disk here), navigates to the one fixed reviewed search-page
    route, and reports AUTHENTICATED / LOGGED_OUT / INDETERMINATE exactly
    as mcma.portal.capabilities._observe_session_state distinguishes them.
    Called here in STRICT mode: an evaluation exception is a setup/probe
    failure (SessionProbeFailed, cause type only), never silently folded
    into INDETERMINATE the way ReadCapability's own (non-strict) callers
    still get it. No portal write is ever attempted.

Both operations always target DEFAULT_SINAUTO_HOST and entity MCMA. There
is no parameter anywhere in this module for host, URL, route, selector,
JavaScript, portal entity, credentials, OTP, or a browser profile path --
a caller cannot widen what gets navigated to or how, only pick which of
the two allowed accounts is being onboarded/verified.

Neither function ever returns a Page, BrowserContext, Browser, or
LoginCapability instance -- those stay entirely inside this module's two
functions. LoginCapability and the shared session-state-observation
helper are reused unchanged from mcma.portal.capabilities; this module
adds no new Playwright script, no new route, and no write contract of its
own. ReadCapability itself is not instantiated here at all -- its public
surface is unchanged, and this module reaches the same underlying
observation logic directly.
"""

from __future__ import annotations

from enum import Enum
from typing import Sequence

from mcma.portal.browser import launch_browser
from mcma.portal.capabilities import (
    SessionMaterial, _observe_session_state, open_login_session, portal_origin,
)
from mcma.portal.session import open_guarded_context
from mcma.portal.sinauto_contracts import (
    DEFAULT_SINAUTO_HOST, auth_contracts, category_discovery_contracts,
)

# mirrors mcma.app.workstation_runner.protocol.RUNNER_ACCOUNT_IDS -- see the
# module docstring above for why this is a fresh literal, not an import.
WORKSTATION_ACCOUNT_IDS = ("acct-mcma-oujda", "acct-mcma-nador")
WORKSTATION_ENTITY = "MCMA"

_SEARCH_PAGE_OPERATION_TYPE = "search_page"

__all__ = [
    "WORKSTATION_ACCOUNT_IDS",
    "WORKSTATION_ENTITY",
    "SessionProbeOutcome",
    "SessionProbeFailed",
    "UnknownWorkstationAccount",
    "InvalidWorkstationStorageState",
    "perform_manual_login",
    "verify_saved_session",
]


class UnknownWorkstationAccount(ValueError):
    """Raised for any account_id outside the fixed two-account allowlist --
    fixed message only, the rejected value is never retained (mirrors
    mcma.app.workstation_runner.session_store.UnknownWorkstationAccount's
    reasoning, independently, since this module may not import that one)."""

    def __init__(self) -> None:
        super().__init__("account_id is not one of the allowed workstation MCMA accounts")


class InvalidWorkstationStorageState(ValueError):
    """storage_state must be an in-memory dict -- never a path, never a
    string, never anything this module could mistake for a file to open.
    Raised before any browser is launched."""

    def __init__(self) -> None:
        super().__init__("storage_state must be a dict produced by Playwright's own storage_state()")


class SessionProbeFailed(Exception):
    """A SETUP or NAVIGATION failure while verifying a saved session --
    deliberately distinct from an actual INDETERMINATE observation (which
    ReadCapability.observe_session_state() itself already returns as a
    plain value, never an exception), so a future caller can map THIS
    exception to ERROR without mistaking a genuine "cannot tell" reading
    for a browser/setup fault.

    Carries only the failing exception's TYPE NAME, never its message: a
    browser-level error can quote page content, and the page behind a
    saved session can be a login form. `raise ... from None` is used at
    every construction site so the original exception's text never
    reaches a caller's traceback."""

    def __init__(self, cause_type: str) -> None:
        super().__init__(f"workstation session verification failed ({cause_type})")
        self.reason = f"SESSION_PROBE_FAILED_{cause_type}"


class SessionProbeOutcome(Enum):
    """The three states ReadCapability.observe_session_state() itself
    distinguishes. An operational failure is never a fourth member here --
    it is SessionProbeFailed, raised instead of returned."""

    AUTHENTICATED = "AUTHENTICATED"
    LOGGED_OUT = "LOGGED_OUT"
    INDETERMINATE = "INDETERMINATE"


def _require_known_account(account_id: object) -> str:
    if not isinstance(account_id, str) or account_id not in WORKSTATION_ACCOUNT_IDS:
        raise UnknownWorkstationAccount()
    return account_id


def _single_search_page_route(contracts: Sequence) -> str:
    """The one reviewed read/search-page contract inside our OWN fixed
    category_discovery_contracts() output -- never a caller-supplied
    contract, so this is an invariant on our own literal, not an input
    validation boundary.

    Checked with an explicit fail-closed raise rather than `assert`:
    `python -O` strips assert statements, which would silently turn a
    drifted/duplicated contract set into undefined navigation behavior in
    an optimized build instead of a guaranteed failure. Fails BEFORE any
    browser is launched, and carries only a fixed cause identifier -- no
    contract, route, or caller content."""
    matches = [c for c in contracts if c.operation_type == _SEARCH_PAGE_OPERATION_TYPE]
    if len(matches) != 1:
        raise SessionProbeFailed("SearchPageContractInvariant")
    return matches[0].route


async def perform_manual_login(
    account_id: str, *, poll_interval_seconds: float = 1.0, timeout_seconds: float = 300.0,
) -> SessionMaterial:
    """Visible manual login + OTP for one fixed, allowed MCMA workstation
    account. The employee enters credentials and OTP directly in the
    headed browser window this opens; this function never accepts, stores,
    transmits, or logs anything about them -- it returns only the existing
    redacted SessionMaterial LoginCapability itself produces once the
    logged-in markers are positively present (never a partial/rejected-
    credential result).

    poll_interval_seconds/timeout_seconds thread straight through to
    LoginCapability.perform_manual_login (same validation, same defaults)
    -- purely a timing knob, never a way to widen what gets navigated to.

    The LoginCapability and the browser are both closed on every exit path
    -- success, timeout, the employee closing the window, an unexpected
    probe failure, or task cancellation. asyncio.CancelledError is a
    BaseException, is never caught here as an ordinary Exception, and
    propagates once cleanup finishes."""
    account_id = _require_known_account(account_id)
    contracts = auth_contracts(DEFAULT_SINAUTO_HOST, WORKSTATION_ENTITY)
    async with launch_browser(headless=False) as browser:
        login = await open_login_session(browser, account_id, contracts, DEFAULT_SINAUTO_HOST)
        try:
            return await login.perform_manual_login(
                poll_interval_seconds=poll_interval_seconds, timeout_seconds=timeout_seconds,
            )
        finally:
            await login.close()


async def verify_saved_session(account_id: str, storage_state: dict) -> SessionProbeOutcome:
    """Headless verification of an already-captured Playwright
    storage_state -- no credentials, no OTP, no portal write. The state is
    applied ONLY in memory, through the guarded context's own creation
    options (Playwright's new_context(storage_state=...) accepts a dict
    directly; this module never writes it to a file).

    Returns exactly the three states the shared _observe_session_state
    helper distinguishes. Unlike ReadCapability.observe_session_state()'s
    own (non-strict) use of that helper, this function calls it with
    strict=True: an evaluation exception is NOT swallowed into
    INDETERMINATE here -- it is a setup/probe failure, never an ambiguous
    observation, and is caught below and re-raised as SessionProbeFailed
    (cause TYPE NAME only) so a future caller can map it to ERROR distinct
    from a genuine INDETERMINATE reading. Page, context, and browser are
    always closed, including on cancellation."""
    account_id = _require_known_account(account_id)
    if not isinstance(storage_state, dict):
        raise InvalidWorkstationStorageState()
    host = DEFAULT_SINAUTO_HOST
    contracts = category_discovery_contracts(host, WORKSTATION_ENTITY)
    search_page_route = _single_search_page_route(contracts)

    async with launch_browser(headless=True) as browser:
        try:
            context = await open_guarded_context(
                browser, contracts, host, context_options={"storage_state": storage_state},
            )
        except Exception as exc:
            raise SessionProbeFailed(type(exc).__name__) from None
        try:
            try:
                page = await context.new_page()
                await page.goto(f"{portal_origin(host)}{search_page_route}")
            except Exception as exc:
                raise SessionProbeFailed(type(exc).__name__) from None
            try:
                observed = await _observe_session_state(page, strict=True)
            except Exception as exc:
                raise SessionProbeFailed(type(exc).__name__) from None
        finally:
            await context.close()
    return SessionProbeOutcome(observed)
