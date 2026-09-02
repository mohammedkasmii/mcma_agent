"""
mcma.portal.capabilities -- LoginCapability and ReadCapability (INC-08,
ADR-0003, SAFETY_MODEL.md §1).

Neither capability exposes a write method, a generic request()/evaluate()
method, the raw BrowserContext/Page, or any path to a writer.
VerifiedMissionWriter and identity verification are INC-09 and do not exist
here. Persistence, lease acquisition, and the DPAPI session vault are
INC-11/INC-13 and are not implemented here either -- LoginCapability does
not acquire, hold, or validate an account lease at all (SAFETY_MODEL.md §1
defines its constructor as `portal.open_login_session(account_id)`, with no
LeaseHandle); it produces only in-memory SessionMaterial and cannot store or
replace a stored session -- that happens later, lease-guarded, in the
INC-13 vault write path (SAFETY_MODEL.md §7). ReadCapability DOES receive a
LeaseHandle and validates it via `assert_valid()` before any context is
created, but this module still never acquires or persists a lease itself.

The four ReadCapability operations (search/open/scrape/read_rows) are
deliberately narrow: typed/validated caller input only, fixed internal
routes and scripts, caller data passed only as serialized page.evaluate()
arguments -- never interpolated into script text, a route, or a selector.

Neither open_login_session's initial navigation nor open_reader's initial
navigation hardcodes a concrete page path in this module.
docs/recovery/PORTAL_CONTRACT.md attests only detection HEURISTICS (a
logged-in/logged-out marker set), never a confirmed navigable page path on
the real portal -- inventing one here would be an unevidenced production
claim. Both functions instead require the caller to supply exactly one
reviewed GET contract for the purpose (capability="auth"/operation_type=
"login_page" for login; capability="read"/operation_type="search_page" for
reading) and navigate to whatever route that contract names. The INC-06
mock's own convention for these routes is recorded in
tests/fixtures/contracts/login_page_navigation_mock_only.json and
read_search_page_navigation_mock_only.json, explicitly classified
MOCK_ONLY/UNCONFIRMED and never eligible for the live allowlist.
"""

from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Protocol, Sequence, runtime_checkable
import re
from urllib.parse import quote, urlsplit

from mcma.domain.enums import RepairWorkflow
from mcma.portal.contracts import RouteContract
from mcma.portal.final_endpoints import is_permanently_blocked
from mcma.portal.identity import ObservedIdentity
from mcma.portal.identity import observe_identity as _observe_identity
from mcma.portal.sinauto_contracts import NOTIFICATION_BODY_FIELDS
from mcma.portal.session import open_guarded_context, open_guarded_context_for_login

if TYPE_CHECKING:  # pragma: no cover - typing only
    from playwright.async_api import Browser


# --------------------------------------------------------------------- #
# Shared contract-scope guard
# --------------------------------------------------------------------- #


def _require_only_capability(contracts: Sequence[RouteContract], expected_capability: str) -> None:
    """Fail closed BEFORE any browser context is created if a contract is
    outside its capability's allowed scope, or targets a permanently
    blocked route (defense in depth on top of the per-request check that
    already runs on every live request -- mcma.portal.contracts.
    evaluate_request)."""
    for contract in contracts:
        if contract.capability != expected_capability:
            raise ValueError(
                f"contract capability {contract.capability!r} is not allowed here "
                f"(expected only {expected_capability!r}): {contract.route}"
            )
        if is_permanently_blocked(contract.route):
            raise ValueError(f"contract route is permanently blocked: {contract.route!r}")


def _validate_positive_finite(value, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a positive, finite number: {value!r}")


# --------------------------------------------------------------------- #
# LeaseHandle (INC-08 amendment #2 -- account_id alone does not prove
# ownership; assert_valid() is the structural proof this module requires)
# --------------------------------------------------------------------- #


@runtime_checkable
class LeaseHandle(Protocol):
    """Structural placeholder for the per-account lease handle acquired by
    execution via persistence (INC-11). This module never acquires,
    reacquires, or persists a lease -- it only threads one through and
    calls assert_valid() before creating any context."""

    account_id: str

    async def assert_valid(self) -> None:
        """Raises if the lease is not currently valid/held."""
        ...


class LeaseInvalid(Exception):
    def __init__(self, account_id: str):
        super().__init__(f"lease for account {account_id!r} is not valid")
        self.account_id = account_id


# --------------------------------------------------------------------- #
# SessionMaterial (INC-08 amendment #1)
# --------------------------------------------------------------------- #


class SessionMaterial:
    """In-memory-only session material produced by
    LoginCapability.perform_manual_login (SAFETY_MODEL.md §7 correction
    #6): the human performs the login and OTP themselves; this only
    captures the resulting browser storage state. Never persisted here.

    Deliberately has no JSON serialization, no file-writing method, a
    redacted repr/str (storage state never appears), and no public
    `storage_state` attribute -- so cookies/tokens cannot leak into logs,
    debuggers, or exception text. `consume_for_handoff()` is the single
    explicit operation the future INC-13 vault uses to take the raw
    material once for validation/encryption; a second call raises rather
    than handing the material out again."""

    __slots__ = ("_account_id", "_storage_state", "_consumed")

    def __init__(self, account_id: str, storage_state: dict):
        self._account_id = account_id
        self._storage_state = storage_state
        self._consumed = False

    @property
    def account_id(self) -> str:
        return self._account_id

    @property
    def consumed(self) -> bool:
        return self._consumed

    def consume_for_handoff(self) -> dict:
        if self._consumed:
            raise RuntimeError(
                f"SessionMaterial for account {self._account_id!r} was already consumed"
            )
        self._consumed = True
        return self._storage_state

    def __repr__(self) -> str:
        return f"SessionMaterial(account_id={self._account_id!r}, consumed={self._consumed})"

    def __str__(self) -> str:
        return self.__repr__()


# --------------------------------------------------------------------- #
# LoginCapability (INC-08 amendment #6 -- narrow, onboarding-only)
# --------------------------------------------------------------------- #

_LOGIN_PAGE_OPERATION_TYPE = "login_page"
# Category discovery (PORTAL_CONTRACT.md §7, recovered from
# browser/notifications.py:203,208 at baseline 0290fe9). The portal does
# not publish a stable list of alert categories anywhere, and this
# repository contains no reviewed fixed list -- the `categories` table
# ships empty -- so the active codes are read from the portal's own
# notification surface.
#
# What comes back is a CODE and nothing else. The href is deliberately
# never returned: portal-supplied data must not be able to become a route
# this agent will navigate to. A code is validated against the recovered
# pattern here AND again by the caller, and can only ever be substituted
# into the one fixed getAlerte route.
# The alert list is populated by its own read; FrontExpert does not
# arrive with it filled in. The baseline made that request through the
# portal's own actualierAlertes()/jQuery .load(); this issues the same
# fixed reviewed read directly instead, so the boundary is a contract in
# this repository rather than a function name on someone else's page.
#
# The response is parsed with DOMParser into a DETACHED document. It is
# never inserted into the live page: DOMParser does not execute scripts,
# so a hostile fragment cannot run, and nothing from it can touch the
# document the capability is standing on.
_CATEGORY_SURFACE_JS = """([url, prefixes]) => fetch(url, {
    method: 'GET',
    headers: {'X-Requested-With': 'XMLHttpRequest'}
}).then(r => r.ok ? r.text() : null).then(html => {
    if (html === null) return null;
    const parsed = new DOMParser().parseFromString(html, 'text/html');
    const links = parsed.querySelectorAll('a[href]');
    const codes = [];
    links.forEach(a => {
        const code = matchCategoryHref(a.getAttribute('href') || '', prefixes);
        if (code) codes.push(code);
    });
    return codes;
}).catch(() => null)"""

_CATEGORY_LINKS_JS = """(prefixes) => {
    const links = document.querySelectorAll('#listeAlertes a[href]');
    const codes = [];
    links.forEach(a => {
        const code = matchCategoryHref(a.getAttribute('href') || '', prefixes);
        if (code) codes.push(code);
    });
    return codes;
}"""

# The one rule both discovery scripts apply to a portal-supplied href.
#
# It is a WHOLE-PATH match, not a prefix test. The href must resolve to
# this origin, and its path must be exactly one of the two reviewed
# category paths followed by one segment that looks like a code:
#
#   <base>/expertise/notification/alerte/<code>
#   <base>/expertise/notification/notification/alerte/<code>
#
# The second shape is the one the real portal renders; the previous guard
# recognised it in the selector but then rejected it on the prefix test,
# which is why discovery still found nothing onsite.
#
# Nothing wider is accepted: an extra segment, a different notification
# path, a query string smuggled into the segment, or a code with a slash
# or a dot in it all fail here rather than being sanitized. And the href
# itself never leaves the page -- only the code does.
_CATEGORY_MATCH_JS = """
function matchCategoryHref(href, prefixes) {
    let resolved;
    try { resolved = new URL(href, location.href); } catch (e) { return null; }
    if (resolved.origin !== location.origin) return null;
    for (const prefix of prefixes) {
        if (resolved.pathname.indexOf(prefix + '/') !== 0) continue;
        const rest = resolved.pathname.slice(prefix.length + 1);
        if (/^[A-Za-z0-9-]+$/.test(rest)) return rest;
    }
    return null;
}
"""

_CATEGORY_SURFACE_JS = f"{_CATEGORY_MATCH_JS}\n({_CATEGORY_SURFACE_JS})"
_CATEGORY_LINKS_JS = f"{_CATEGORY_MATCH_JS}\n({_CATEGORY_LINKS_JS})"

_CATEGORY_CODE_PATTERN = re.compile(r"^[A-Za-z0-9-]+$")


def is_valid_category_code(value) -> bool:
    """A code may be substituted into the getAlerte route only if it looks
    like a code. Applied to CONFIGURED codes as well as discovered ones:
    a value from a settings file is no more trustworthy as a URL segment
    than one from the portal, and percent-encoding alone is not the
    defence -- `..%2Fevil` is still not a category.

    The value is judged EXACTLY as given, with no strip() first. The route
    is built from the original string, so validating a trimmed copy would
    accept " CODE-1 " and then fetch `%20CODE-1%20` -- a check that passes
    on a different value than the one used is not a check. A caller with
    whitespace around its code has a malformed code, and fixing it here
    would be repairing input this layer has no authority to interpret.
    """
    return isinstance(value, str) and _CATEGORY_CODE_PATTERN.fullmatch(value) is not None
_MAX_DISCOVERED_CATEGORIES = 50

# Session state (recovered from browser/mission_navigator.py's
# check_session_validity() at baseline 0290fe9). The logged-OUT evidence
# is that function's three indicators verbatim; the logged-IN markers are
# the ones already used for manual login.
#
# Returns booleans only. No URL, no HTML, no DOM: this page can be a
# login form holding a username, a password and an OTP, and none of that
# is anything to read, log or return.
# Evidence of an authenticated portal page.
#
# The original three markers came from the search form. Onsite, the real
# frontexpert page presented NONE of them to the probe while being
# unmistakably signed in -- the debug run on 2026-09-02 showed
# `listeAlertes exists = True` and `typeof actualierAlertes = function`
# on that very page with a session minted minutes earlier. With no
# logged-in marker and no logged-out marker the probe answered
# INDETERMINATE, the poll returned PORTAL_UNAVAILABLE before run_poll,
# and no poll_run was ever recorded. That is the exact failure shape:
# "refresh says unavailable, poll_runs never grows".
#
# #listeAlertes is the alert navbar of the authenticated application and
# actualierAlertes() is the portal's own function that populates it. The
# golden extractor (browser/notifications.py @ 5d12c3d) discovers from
# exactly that element. Neither exists on a login page, so adding them as
# logged-in evidence narrows nothing and guesses nothing: it records what
# the real authenticated page was observed to contain.
_SESSION_STATE_JS = """() => {
    const url = (location.href || '').toLowerCase();
    const html = document.documentElement ? document.documentElement.innerHTML : '';
    const markerPresent = ['#formRecherche', '#ReferenceCie', "a[href*='logout']", '#listeAlertes']
        .some(sel => document.querySelector(sel) !== null);
    const alertFunctionPresent = typeof window.actualierAlertes === 'function';
    return {
        logged_in: markerPresent || alertFunctionPresent,
        logged_out: url.indexOf('login') !== -1
            || document.querySelector("input[name='login'], #login, #password") !== null
            || html.indexOf('expert_.phtml') !== -1
    };
}"""

_LOGGED_IN_MARKER_JS = """(selectors) => selectors.some(sel => document.querySelector(sel) !== null)"""
LOGGED_IN_MARKERS = ("#formRecherche", "#ReferenceCie", "a[href*='logout']", "#listeAlertes")


def _find_single_navigation_route(
    contracts: Sequence[RouteContract], *, capability: str, operation_type: str
) -> str:
    """The one GET route a capability is allowed to navigate its page to at
    construction time, derived strictly from the caller's own reviewed
    contracts -- never a path hardcoded in this module. A concrete
    navigable page path is not something PORTAL_CONTRACT.md attests for
    the real portal (it attests detection heuristics, not paths), so this
    module never invents one; the caller must supply a contract for it
    (tests/fixtures/contracts/login_page_navigation_mock_only.json and
    read_search_page_navigation_mock_only.json record the INC-06 mock's
    own convention, explicitly classified as MOCK_ONLY/UNCONFIRMED, never
    eligible for the live allowlist). Zero or more than one match fails
    closed: an ambiguous navigation target is never guessed at."""
    matches = [
        c
        for c in contracts
        if c.capability == capability and c.method == "GET" and c.operation_type == operation_type
    ]
    if len(matches) != 1:
        raise ValueError(
            f"exactly one reviewed GET {capability!r} contract with "
            f"operation_type={operation_type!r} is required to navigate "
            f"(found {len(matches)})"
        )
    return matches[0].route


class LoginTimedOut(Exception):
    def __init__(self, account_id: str):
        super().__init__(f"manual login for account {account_id!r} timed out")
        self.account_id = account_id
        self.reason = "LOGIN_TIMED_OUT"


class LoginWindowClosed(Exception):
    """The human closed the login window. A deliberate cancellation, not a
    failure, and reported immediately rather than after the full
    timeout."""

    def __init__(self, account_id: str):
        super().__init__(f"the login window for account {account_id!r} was closed")
        self.account_id = account_id
        self.reason = "LOGIN_WINDOW_CLOSED"


class LoginProbeFailed(Exception):
    """The logged-in probe failed for a reason that is neither a normal
    navigation nor a closed window.

    Carries only the ORIGINAL EXCEPTION'S TYPE NAME, never its message:
    a browser error can quote page content, and this page is a login form
    holding a username, a password and an OTP. The original is chained for
    a local traceback and never reaches a caller's output."""

    def __init__(self, account_id: str, cause_type: str):
        super().__init__(f"login probe failed for account {account_id!r} ({cause_type})")
        self.account_id = account_id
        self.reason = f"LOGIN_PROBE_FAILED_{cause_type}"


# Playwright raises plain Errors whose TYPE does not distinguish these
# cases, so they are told apart by the fixed phrases its driver emits.
# Matching on the message is not ideal; the alternative is treating a
# routine page reload as a fatal login failure, which is what happened.
_TRANSIENT_PROBE_PHRASES = (
    "execution context was destroyed",
    "cannot find context with specified id",
    "execution context is not available",
    "most likely because of a navigation",
    "frame was detached",
    "navigation",
)

_CLOSED_PROBE_PHRASES = (
    "target closed",
    "target page, context or browser has been closed",
    "page has been closed",
    "browser has been closed",
    "context has been closed",
)


class LoginCapability:
    """Desktop onboarding tool only (SAFETY_MODEL.md §1). Navigates ONLY to
    the single reviewed GET login-page route supplied in its contracts
    (open_login_session requires exactly one) and polls ONLY the fixed
    logged-in markers above. It never accepts a credential argument, never
    fills a form, never accepts an arbitrary URL/selector, and never opens
    a mission page -- the human performs login and OTP themselves."""

    def __init__(self, context, page, account_id: str):
        self._context = context
        self._page = page
        self._account_id = account_id
        self._closed = False

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("LoginCapability is closed")

    async def perform_manual_login(
        self,
        *,
        poll_interval_seconds: float = 1.0,
        timeout_seconds: float = 300.0,
        sleep=None,
    ) -> SessionMaterial:
        self._ensure_open()
        _validate_positive_finite(poll_interval_seconds, "poll_interval_seconds")
        _validate_positive_finite(timeout_seconds, "timeout_seconds")
        sleep = sleep or asyncio.sleep
        elapsed = 0.0
        while True:
            if self._page_is_closed():
                # The human cancelled. Reported at once rather than after
                # the remaining timeout.
                raise LoginWindowClosed(self._account_id)

            if await self._is_logged_in():
                # Session material is produced ONLY here, after the
                # logged-in markers are positively present. A rejected
                # password never reaches this line, so nothing partial is
                # ever captured.
                storage_state = await self._context.storage_state()
                return SessionMaterial(self._account_id, storage_state)

            if elapsed >= timeout_seconds:
                raise LoginTimedOut(self._account_id)
            await sleep(poll_interval_seconds)
            elapsed += poll_interval_seconds

    def _page_is_closed(self) -> bool:
        is_closed = getattr(self._page, "is_closed", None)
        if is_closed is None:
            return False
        try:
            return bool(is_closed())
        except Exception:
            return False

    async def _is_logged_in(self) -> bool:
        """Answers one question -- are the logged-in markers present -- and
        treats a page that is mid-navigation as "not yet".

        Submitting credentials navigates the page, which destroys the
        JavaScript execution context this probe runs in. Letting that
        exception escape ended the whole attempt: a mistyped password
        closed the window and returned an error, when the employee should
        simply have been able to try again. A rejected credential is the
        expected case on a login form, not a fault."""
        try:
            return bool(await self._page.evaluate(_LOGGED_IN_MARKER_JS, list(LOGGED_IN_MARKERS)))
        except Exception as exc:
            if self._page_is_closed():
                raise LoginWindowClosed(self._account_id) from exc
            message = str(exc).lower()
            if any(phrase in message for phrase in _CLOSED_PROBE_PHRASES):
                raise LoginWindowClosed(self._account_id) from exc
            if any(phrase in message for phrase in _TRANSIENT_PROBE_PHRASES):
                # The page is loading; look again on the next tick.
                return False
            # Anything else is genuinely unexpected and is NOT swallowed.
            raise LoginProbeFailed(self._account_id, type(exc).__name__) from exc

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            await self._context.close()
        except Exception:
            # The human may already have closed the window; tearing down
            # something that is gone is not an error worth raising over a
            # real outcome that is being reported.
            pass


def portal_origin(allowed_host: str) -> str:
    """The origin to navigate to for `allowed_host`.

    The scheme was hardcoded to http:// throughout this module, written
    when the only reachable host was mock_server.py on loopback. Pointed
    at the real portal that navigates to http://sinauto.mamda-mcma.ma,
    which does not serve plain HTTP -- the page never loads, the
    capability is closed, and the window the employee is looking at shuts
    on about:blank with no explanation.

    Loopback keeps http (the mock serves exactly that); every other host
    is https, because a real portal carrying claimant data over plain
    HTTP is not a case worth supporting. The guard itself is unaffected
    either way: evaluate_request matches on host, path and method and
    never on the scheme, so this changes where a request goes, never what
    is permitted."""
    hostname = urlsplit(f"//{allowed_host}").hostname
    if hostname in ("127.0.0.1", "::1", "localhost"):
        return f"http://{allowed_host}"
    return f"https://{allowed_host}"


async def open_login_session(
    browser: "Browser",
    account_id: str,
    contracts: Sequence[RouteContract],
    allowed_host: str,
    *,
    context_options: dict | None = None,
) -> LoginCapability:
    if not isinstance(account_id, str) or not account_id.strip():
        raise ValueError("account_id must be a non-empty string")
    frozen_contracts = tuple(contracts)
    _require_only_capability(frozen_contracts, "auth")
    login_page_route = _find_single_navigation_route(
        frozen_contracts, capability="auth", operation_type=_LOGIN_PAGE_OPERATION_TYPE
    )
    # A human sign-in needs the portal's own login flow to work; see
    # install_login_guard for exactly how that policy differs and what
    # stays blocked.
    context = await open_guarded_context_for_login(browser, allowed_host, context_options)
    try:
        page = await context.new_page()
        await page.goto(f"{portal_origin(allowed_host)}{login_page_route}")
    except Exception:
        await context.close()
        raise
    return LoginCapability(context, page, account_id)


# --------------------------------------------------------------------- #
# ReadCapability (INC-08 amendment #3 -- no generic escape hatches)
# --------------------------------------------------------------------- #


@dataclass(frozen=True)
class SearchIdentifiers:
    """Typed/validated search input -- never a raw caller-supplied dict."""

    matricule: str = ""
    reference_cie: str = ""

    def __post_init__(self):
        if not isinstance(self.matricule, str) or not isinstance(self.reference_cie, str):
            raise TypeError("SearchIdentifiers fields must be strings")
        if not self.matricule.strip() and not self.reference_cie.strip():
            raise ValueError("SearchIdentifiers requires at least one non-empty identifier")


class ApprovedField(Enum):
    """The closed set of scrapeable fields; each maps internally to one
    fixed, reviewed CSS selector -- a caller never supplies a selector."""

    MATRICULE_VEH = "MATRICULE_VEH"
    REFERENCE_DOSSIER = "REFERENCE_DOSSIER"
    MODE_REPARATION = "MODE_REPARATION"
    REF_SINISTRE = "REF_SINISTRE"


_APPROVED_FIELD_SELECTORS = {
    ApprovedField.MATRICULE_VEH: "#MatriculeVeh",
    ApprovedField.REFERENCE_DOSSIER: "#ReferenceDossier",
    ApprovedField.MODE_REPARATION: "#modeReparation",
    ApprovedField.REF_SINISTRE: "#hdrRefSinistre",
}


class Candidate:
    """An opaque search result. Only mintable by ReadCapability.search() --
    every Candidate carries the owner_token of the specific ReadCapability
    instance that minted it, and ReadCapability.open() rejects any
    Candidate whose token does not match. Deliberately carries no
    route/URL field of any kind: open() derives navigation from
    `id_mission` (a percent-escaped scalar) through one fixed internal
    template only."""

    __slots__ = ("_id_mission", "_matricule", "_reference_mission", "_societaire", "_owner_token")

    def __init__(self, *, id_mission, matricule, reference_mission, societaire, owner_token):
        self._id_mission = id_mission
        self._matricule = matricule
        self._reference_mission = reference_mission
        self._societaire = societaire
        self._owner_token = owner_token

    @property
    def id_mission(self):
        return self._id_mission

    @property
    def matricule(self):
        return self._matricule

    @property
    def reference_mission(self):
        return self._reference_mission

    @property
    def societaire(self):
        return self._societaire


_SEARCH_PAGE_OPERATION_TYPE = "search_page"
_SEARCH_ROUTE = "/SinAuto_MCMA/expertise/FrontExpert/listeMissions"
_MISSION_DEEP_LINK_TEMPLATE = (
    "/SinAuto_MCMA/expertise/gestionExpert/getSinistre/idSinistre/{id_sinistre}/rubrique/gestionexpert-index"
)
_ROW_LIST_ROUTES = {
    RepairWorkflow.MODE_NORMAL: "/SinAuto_MCMA/expertise/gestionExpert/listeRapportDefDet",
    RepairWorkflow.GARAGE_CONVENTIONNE: "/SinAuto_MCMA/expertise/gestiongarage/listeDevisDet",
}

# INC-14: PORTAL_CONTRACT.md §7's recovered getAlerte/DataTable contract.
# The path segment is a validated, percent-escaped code_alerte -- the
# caller must supply a matching reviewed RouteContract for the exact
# category code(s) they poll (category-scoped, same discipline as every
# other dynamic route in this project).
# MCMA and MAMDA are two applications on ONE host, distinguished by their
# base path: /SinAuto_MCMA and /SinAuto_MAMDA. Hardcoding the MCMA prefix
# sent every MAMDA account to MCMA's pages -- all four login buttons
# landed on the same form, and a MAMDA notification poll would have read
# MCMA's alert list.
DEFAULT_PORTAL_BASE = "/SinAuto_MCMA"

_NOTIFICATION_ROUTE_TEMPLATE = "{base}/expertise/notification/getAlerte/CodeAlerte/{code}"

_FETCH_JSON_JS = """([url, payload]) => fetch(url, {
    method: 'POST',
    headers: {'Content-Type': 'application/x-www-form-urlencoded'},
    body: new URLSearchParams(payload).toString()
}).then(r => r.json())"""

# The getAlerte request exactly as the proven extractor issues it
# (browser/notifications.py at 5d12c3d). The headers are not decoration:
# without X-Requested-With the portal answers with an HTML page rather
# than the DataTable JSON, and the charset on the content type is what
# the working request sent.
#
# The response is returned as TEXT and parsed here rather than with
# r.json(), so a non-JSON body (a session-expired login page) becomes a
# recognisable failure instead of a rejected promise with no shape.
_NOTIFICATION_FETCH_JS = """([url, payload]) => fetch(url, {
    method: 'POST',
    headers: {
        'X-Requested-With': 'XMLHttpRequest',
        'Accept': 'application/json, text/javascript, */*',
        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8'
    },
    body: new URLSearchParams(payload).toString()
}).then(async r => {
    // The status is checked BEFORE the body is looked at, as the proven
    // extractor does. A 401/403/500 often still carries a JSON-ish body,
    // and a body of {"data":[]} from an expired session would otherwise
    // read as "this category is clear" and retire real notifications.
    if (!r.ok) return {ok: false, status: r.status};
    const text = await r.text();
    try { return {ok: true, parsed: JSON.parse(text)}; }
    catch (e) { return {ok: false}; }
}).catch(() => ({ok: false}))"""

# The full-dataset parameters the proven extractor sends. length=-1 asks
# DataTables for every row; the duplicated iDisplay*/rows/limit/page/draw
# names are what the real portal answered to, and are kept verbatim
# rather than trimmed to the ones that look sufficient.
_NOTIFICATION_FULL_DATASET_VALUES = {
    "length": "-1",
    "start": "0",
    "iDisplayLength": "-1",
    "iDisplayStart": "0",
    "rows": "999999",
    "limit": "999999",
    "page": "1",
    "draw": "1",
}

# Ordered by the contract's own field tuple, and asserted to cover it
# exactly. The interceptor compares body_fields for equality, so a field
# added here and not there (or the reverse) is a denied request rather
# than a loose one -- this makes that mismatch impossible at import time
# instead of at the agency.
assert set(_NOTIFICATION_FULL_DATASET_VALUES) == set(NOTIFICATION_BODY_FIELDS), (
    "the notification request body and its route contract have drifted apart"
)

_NOTIFICATION_FULL_DATASET_PAYLOAD = {
    field: _NOTIFICATION_FULL_DATASET_VALUES[field] for field in NOTIFICATION_BODY_FIELDS
}


def _notification_rows_from_payload(parsed):
    """The three shapes the real portal was observed to answer with:
    a bare array, {"data": [...]} and {"rows": [...]}.

    Returns None for anything else -- including a dict with a non-list
    `data`. None means FAILED at the caller, never zero rows: an empty
    result is evidence a category is clear, and a session-expired page
    must never be able to produce it."""
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        for key in ("data", "rows"):
            value = parsed.get(key)
            if isinstance(value, list):
                return value
    return None

_SCRAPE_JS = """(pairs) => {
    const out = {};
    for (const [name, sel] of pairs) {
        const el = document.querySelector(sel);
        out[name] = el ? (el.value !== undefined ? el.value : el.textContent) : null;
    }
    return out;
}"""


class ReadCapability:
    """Deny-by-default (SAFETY_MODEL.md §1). Exposes ONLY search, open,
    scrape, read_rows, and close. No write method, no generic request()/
    evaluate(), no raw context/page, no upgrade-to-writer path. Every
    operation reaches the portal only through a fixed internal route and a
    fixed internal script; caller input is always passed as a serialized
    page.evaluate() argument, never interpolated into script text, a
    route, or a selector.

    `open_reader` navigates this capability's page to a caller-supplied,
    contract-reviewed GET route immediately after creation (before
    returning the capability), establishing a same-origin document before
    any fetch-based operation runs. A page that has never navigated stays
    at `about:blank`, which has an opaque/null origin; a `fetch()` from
    that origin to any host -- including an otherwise-correctly-allowed
    one -- is a cross-origin request the browser's own Same-Origin Policy
    rejects unless the target sends matching CORS headers, independent of
    and prior to this module's own interception policy. Navigating first
    makes every subsequent fetch same-origin, which needs no CORS headers
    at all."""

    def __init__(self, context, page, allowed_host: str, portal_base: str = DEFAULT_PORTAL_BASE):
        self._context = context
        self._page = page
        self._allowed_host = allowed_host
        self._portal_base = portal_base
        self._closed = False
        self._capability_token = object()

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("ReadCapability is closed")

    def _absolute_url(self, path: str) -> str:
        return f"{portal_origin(self._allowed_host)}{path}"

    async def _fetch_json(self, route: str, payload: dict) -> dict:
        return await self._page.evaluate(_FETCH_JSON_JS, [self._absolute_url(route), payload])

    async def search(self, identifiers: SearchIdentifiers) -> tuple[Candidate, ...]:
        self._ensure_open()
        if not isinstance(identifiers, SearchIdentifiers):
            raise TypeError("search() requires a SearchIdentifiers instance")
        payload = {"Matricule": identifiers.matricule, "ReferenceCie": identifiers.reference_cie}
        result = await self._fetch_json(_SEARCH_ROUTE, payload)
        rows = result.get("data", []) if isinstance(result, dict) else []
        candidates = []
        for row in rows:
            if not isinstance(row, dict) or "IdMission" not in row:
                continue
            candidates.append(
                Candidate(
                    id_mission=row.get("IdMission"),
                    matricule=row.get("Matricule"),
                    reference_mission=row.get("ReferenceMission"),
                    societaire=row.get("Societaire"),
                    owner_token=self._capability_token,
                )
            )
        return tuple(candidates)

    async def open(self, candidate: Candidate) -> None:
        self._ensure_open()
        if not isinstance(candidate, Candidate):
            raise TypeError("open() only accepts a Candidate, never a caller-supplied URL/string")
        if candidate._owner_token is not self._capability_token:
            raise ValueError(
                "open() only accepts a Candidate returned by this capability's own search()"
            )
        id_segment = quote(str(candidate.id_mission), safe="")
        path = _MISSION_DEEP_LINK_TEMPLATE.format(id_sinistre=id_segment)
        await self._page.goto(self._absolute_url(path))

    async def scrape(self, fields: Sequence[ApprovedField]) -> dict:
        self._ensure_open()
        fields = tuple(fields)
        if isinstance(fields, (str, bytes)) or not fields or not all(
            isinstance(f, ApprovedField) for f in fields
        ):
            raise TypeError("scrape() only accepts one or more ApprovedField members")
        pairs = [(f.value, _APPROVED_FIELD_SELECTORS[f]) for f in fields]
        return await self._page.evaluate(_SCRAPE_JS, pairs)

    async def observe_identity(self) -> ObservedIdentity:
        """The read-only identity gate for the real DRY_RUN job runner
        (pilot-integration correction, section 3): scrapes registration
        and id_sinistre from the currently-open mission page via the one
        fixed script in mcma.portal.identity -- the same scraping this
        capability's write-side counterpart (mcma.portal.writer via
        open_verified_writer) already uses for EXECUTE. Still no raw
        page/context exposure: the fixed script runs, the typed result
        comes back, nothing else."""
        self._ensure_open()
        return await _observe_identity(self._page)

    async def discover_notification_categories(self) -> tuple[str, ...]:
        """The alert category codes this account's portal currently
        offers, read from its own notification surface.

        Returns CODES ONLY. The DOM's hrefs never leave the page: nothing
        portal-supplied becomes a URL this capability will fetch. Each
        code must match the recovered [A-Za-z0-9-]+ pattern exactly --
        anything else is dropped rather than sanitized, since a code that
        does not look like a code is not something to guess at. The
        result is capped, so a compromised or malformed page cannot turn
        one poll into thousands of requests.

        Discovering a code does not authorize fetching it. The caller must
        still install a reviewed RouteContract for that exact category
        before any read can happen, which is why discovery and fetching
        use two separate contexts."""
        self._ensure_open()

        # The reviewed read first -- this is what actually populates the
        # surface. A guarded context with no contract for it returns None
        # here rather than raising, so a blocked read is simply "no codes
        # from this source" and never a crash.
        collected = []
        surface_route = self._notification_surface_route()
        prefixes = self._category_path_prefixes()
        fetched = await self._page.evaluate(
            _CATEGORY_SURFACE_JS, [self._absolute_url(surface_route), prefixes]
        )
        if isinstance(fetched, list):
            collected.extend(fetched)

        # Then the live page, for a portal that populated the navbar on
        # its own. Costs no request and cannot introduce a route.
        in_page = await self._page.evaluate(_CATEGORY_LINKS_JS, prefixes)
        if isinstance(in_page, list):
            collected.extend(in_page)

        codes = []
        for value in collected:
            if not isinstance(value, str):
                continue
            candidate = value.strip()
            if _CATEGORY_CODE_PATTERN.match(candidate) and candidate not in codes:
                codes.append(candidate)
            if len(codes) >= _MAX_DISCOVERED_CATEGORIES:
                break
        return tuple(codes)

    async def observe_session_state(self) -> str:
        """AUTHENTICATED, LOGGED_OUT or INDETERMINATE.

        The distinction this exists for: an empty alert list means one of
        two completely different things. An authenticated account with no
        open alerts is normal. A session that has silently expired and
        redirected to a login page ALSO produces no category links -- and
        reporting that as "no categories" tells the employee everything is
        fine while their notifications quietly stop arriving.

        Contradictory evidence returns INDETERMINATE rather than picking a
        side. Guessing AUTHENTICATED would hide an expired session;
        guessing LOGGED_OUT would revoke a working one and force a
        pointless re-login. Neither is worth a guess, and the caller
        treats INDETERMINATE as "cannot tell, change nothing"."""
        self._ensure_open()
        try:
            state = await self._page.evaluate(_SESSION_STATE_JS)
        except Exception:
            # A page that cannot even be probed says nothing about whether
            # the session is valid.
            return "INDETERMINATE"
        if not isinstance(state, dict):
            return "INDETERMINATE"
        logged_in = bool(state.get("logged_in"))
        logged_out = bool(state.get("logged_out"))
        if logged_out and not logged_in:
            return "LOGGED_OUT"
        if logged_in and not logged_out:
            return "AUTHENTICATED"
        return "INDETERMINATE"

    def _notification_surface_route(self) -> str:
        return f"{self._portal_base}/expertise/notification/alerte"

    def _category_path_prefixes(self) -> list[str]:
        """The two category paths the real portal was observed to render.
        Both are anchored on THIS account's application base, so a MAMDA
        reader can never accept an MCMA category link."""
        return [
            f"{self._portal_base}/expertise/notification/alerte",
            f"{self._portal_base}/expertise/notification/notification/alerte",
        ]

    async def read_notifications(self, code_alerte: str) -> tuple[dict, ...]:
        """INC-14: the recovered getAlerte/DataTable contract
        (PORTAL_CONTRACT.md §7), read-only -- length=-1 asks for the full
        dataset (completeness evidence for the poll-run lifecycle), never
        a mutating request. The caller must have installed a reviewed
        RouteContract for this exact category's route (category-scoped).

        A response shaped unlike the expected DataTable payload (missing
        `data`, or not an object at all -- e.g. a session-expired error
        page/JSON) is a FAILURE, never "zero rows": silently treating it
        as an empty-but-complete result would let a poller's caller
        (mcma.notifications.presence's three-poll lifecycle) advance the
        absence counter and eventually mark real, still-open notifications
        RESOLVED_ON_PORTAL purely because the session had expired. Raising
        here is what makes extract.py's existing except-classifies-FAILED
        path apply to this case too (Fable review finding, INC-15
        correction)."""
        self._ensure_open()
        if not isinstance(code_alerte, str) or not code_alerte.strip():
            raise TypeError("read_notifications() requires a non-empty code_alerte string")
        # Validated HERE too, at the boundary that builds the route, so a
        # code that reached this method from anywhere -- discovery, a
        # settings file, a future caller -- cannot become a path segment
        # without looking like a code. Percent-encoding is not the check:
        # `..%2Fevil` encodes cleanly and is still not a category.
        if not is_valid_category_code(code_alerte):
            raise ValueError("read_notifications() rejected a malformed category code")
        route = _NOTIFICATION_ROUTE_TEMPLATE.format(
            base=self._portal_base, code=quote(code_alerte, safe="")
        )
        outcome = await self._page.evaluate(
            _NOTIFICATION_FETCH_JS,
            [self._absolute_url(route), dict(_NOTIFICATION_FULL_DATASET_PAYLOAD)],
        )
        rows = None
        if isinstance(outcome, dict) and outcome.get("ok"):
            rows = _notification_rows_from_payload(outcome.get("parsed"))
        if rows is None:
            raise ValueError(
                "notification fetch returned a malformed/incomplete payload -- treating as a failed poll"
            )
        # Rows are returned as they arrived. A non-dict row is evidence,
        # and run_poll() already records it through the malformed/unmatched
        # path; dropping it here would lose that evidence and make
        # rows_seen disagree with what the portal actually sent.
        return tuple(rows)

    async def read_rows(self, workflow: RepairWorkflow) -> tuple[dict, ...]:
        self._ensure_open()
        if not isinstance(workflow, RepairWorkflow):
            raise TypeError("read_rows() requires a RepairWorkflow member")
        route = _ROW_LIST_ROUTES.get(workflow)
        if route is None:  # pragma: no cover - exhaustive today; defensive against future members
            raise ValueError(f"no confirmed row-list route for workflow: {workflow!r}")
        result = await self._fetch_json(route, {})
        data = result.get("data", []) if isinstance(result, dict) else []
        return tuple(data)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._context.close()


async def open_reader(
    browser: "Browser",
    lease_handle: LeaseHandle,
    contracts: Sequence[RouteContract],
    allowed_host: str,
    *,
    context_options: dict | None = None,
    portal_base: str = DEFAULT_PORTAL_BASE,
) -> ReadCapability:
    if not isinstance(lease_handle, LeaseHandle):
        raise TypeError("open_reader() requires a LeaseHandle")
    await lease_handle.assert_valid()
    frozen_contracts = tuple(contracts)
    _require_only_capability(frozen_contracts, "read")
    search_page_route = _find_single_navigation_route(
        frozen_contracts, capability="read", operation_type=_SEARCH_PAGE_OPERATION_TYPE
    )
    context = await open_guarded_context(browser, frozen_contracts, allowed_host, context_options)
    try:
        page = await context.new_page()
        await page.goto(f"{portal_origin(allowed_host)}{search_page_route}")
    except Exception:
        await context.close()
        raise
    return ReadCapability(context, page, allowed_host, portal_base)
