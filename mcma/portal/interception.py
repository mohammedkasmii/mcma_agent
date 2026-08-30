"""
mcma.portal.interception -- the async Playwright adapter and the single
safe public installer for the context-level default-deny network policy
(INC-07, ADR-0004, SAFETY_MODEL.md §3).

Only `install_portal_guard` and `hardened_context_options` are public. A
future capability (INC-08+) calls `hardened_context_options()` when opening
`browser.new_context(**options)`, then calls `install_portal_guard(context,
contracts, allowed_host)` immediately -- one call installs BOTH HTTP
default-deny interception and WebSocket denial, so the two can never be
forgotten independently. If either installation step fails, the context is
closed and the exception re-raised: a partially-guarded context must never
remain usable.

Everything here is installed on the BrowserContext (`context.route`,
`context.route_web_socket`), never on a Page, so popups/new tabs/iframes
created from that context are covered by the same policy automatically
(a Playwright guarantee of context-level routing).
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Sequence

from mcma.portal.canonical import canonicalize_request
from mcma.portal.contracts import Decision, RouteContract, evaluate_request
from mcma.portal.final_endpoints import is_permanently_blocked

if TYPE_CHECKING:  # pragma: no cover - typing only, no runtime import needed
    from playwright.async_api import BrowserContext, Route, WebSocketRoute


def hardened_context_options(requested: dict | None = None) -> dict:
    """Options that MUST be passed to browser.new_context(). service_workers
    is forced to "block" and can never be silently replaced: a caller
    supplying a conflicting value is rejected outright, not corrected,
    because silently overriding a caller's explicit (wrong) choice could
    mask a real bug in the caller."""
    options = dict(requested or {})
    existing = options.get("service_workers")
    if existing is not None and existing != "block":
        raise ValueError(
            f"service_workers={existing!r} conflicts with the mandatory 'block' policy"
        )
    options["service_workers"] = "block"
    return options


def _content_type_of(request) -> str | None:
    headers = request.headers
    if not headers:
        return None
    for key, value in headers.items():
        if key.lower() == "content-type":
            return value
    return None


def _canonical_or_none(request):
    try:
        return canonicalize_request(
            raw_url=request.url,
            raw_method=request.method,
            raw_content_type=_content_type_of(request),
            raw_body=request.post_data,
        )
    except Exception:
        return None


_POLICY_DENY_ERROR = "blockedbyclient"  # distinguishes a deliberate guard
# denial from a generic transport failure in every future log/devtools trace.


def _make_route_handler(contracts: Sequence[RouteContract], allowed_host: str):
    """Returns the actual context.route() handler. Any exception anywhere in
    this function -- descriptor extraction, decision evaluation, an
    unexpectedly broken `contracts` argument, or continue_()/abort() itself
    raising -- results in abort(), never an escaped exception and never a
    fall-through continue()."""

    async def handler(route: "Route") -> None:
        request = route.request
        try:
            canonical = _canonical_or_none(request)
            decision = evaluate_request(canonical, contracts, allowed_host)
        except Exception:
            await _abort_never_raising(route)
            return
        try:
            if decision is Decision.ALLOW:
                await route.continue_()
            else:
                await route.abort(_POLICY_DENY_ERROR)
        except Exception:
            await _abort_never_raising(route)

    return handler


async def _abort_never_raising(route: "Route") -> None:
    """Best-effort fail-closed abort that itself never raises: whatever
    already went wrong, the handler coroutine must still return normally
    rather than let an exception escape (an escaped exception is exactly
    what produces the ambiguous, un-attributable net::ERR_FAILED this
    function exists to prevent)."""
    try:
        await route.abort(_POLICY_DENY_ERROR)
    except Exception:
        pass


async def _deny_websocket(ws_route: "WebSocketRoute") -> None:
    """Blocks WebSockets by default. No allowed WebSocket contract is
    invented in this increment -- every WS connection attempt is closed."""
    await ws_route.close()


async def install_portal_guard(
    context: "BrowserContext",
    contracts: Sequence[RouteContract],
    allowed_host: str,
) -> None:
    """The single public installer: context-level HTTP default-deny
    interception AND WebSocket denial, installed together. On any failure,
    the context is closed before the exception propagates."""
    try:
        await context.route("**/*", _make_route_handler(contracts, allowed_host))
        await context.route_web_socket("**/*", _deny_websocket)
    except Exception:
        await context.close()
        raise


# --------------------------------------------------------------------- #
# WriterPolicyController -- explicit-phase, one-way policy state machine
# (INC-09B amendment #1). This is an INTERNAL BUILDING BLOCK for
# mcma.portal.writer's own construction sequence, not a general-purpose
# staged-policy API: install_portal_guard/open_guarded_context above are
# completely unmodified (zero diff) and remain the only mechanism any
# other capability (LoginCapability, ReadCapability) ever uses.
#
# There is deliberately no operation that replaces or arbitrarily widens
# the active contract set. Only three transitions exist, each usable at
# most once (abort_deny_all is the sole exception -- idempotent, callable
# from any phase including ABORTED itself):
#
#   SEARCH_READ --authorize_exact_mission_route()--> MISSION_READ
#   MISSION_READ --activate_write_once()----------> WRITE_ACTIVE
#   (any phase) --abort_deny_all()-----------------> ABORTED
#
# Per amendment #1, the row_write/native_recalc contract tuple is
# validated and frozen by the CALLER (mcma.portal.writer) BEFORE any
# BrowserContext exists, and handed to this controller's constructor
# already-frozen; activate_write_once() takes no argument and cannot
# introduce anything new -- it only flips the phase and exposes the
# tuple that was frozen at construction time.
# --------------------------------------------------------------------- #

MISSION_OPEN_OPERATION_TYPE = "mission_open"


class WriterPolicyPhase(Enum):
    SEARCH_READ = "search_read"
    MISSION_READ = "mission_read"
    WRITE_ACTIVE = "write_active"
    ABORTED = "aborted"


class PolicyPhaseError(Exception):
    """A transition was attempted from a phase that does not permit it
    (e.g. authorizing the mission route twice, activating write before
    mission authorization, or activating write twice)."""


class WriterPolicyController:
    """Not a general-purpose staged-policy API -- see module note above.
    Only mcma.portal.writer constructs and holds a direct reference to
    this class; the writer instance itself is only ever given an
    AbortOnlyHandle wrapping one (below)."""

    def __init__(
        self,
        search_read_contracts: Sequence[RouteContract],
        frozen_write_contracts: Sequence[RouteContract],
        allowed_host: str,
    ) -> None:
        self._phase = WriterPolicyPhase.SEARCH_READ
        self._active_contracts: tuple[RouteContract, ...] = tuple(search_read_contracts)
        self._frozen_write_contracts: tuple[RouteContract, ...] = tuple(frozen_write_contracts)
        self._allowed_host = allowed_host

    @property
    def phase(self) -> WriterPolicyPhase:
        return self._phase

    @property
    def frozen_write_contracts(self) -> tuple[RouteContract, ...]:
        """The already-validated write/native-recalc contracts frozen at
        construction time -- exposed read-only so activate_write_once()
        can be shown to introduce nothing new."""
        return self._frozen_write_contracts

    def contracts(self) -> tuple[RouteContract, ...]:
        """Read fresh by the route handler on every single request. Once
        ABORTED, this is unconditionally empty regardless of what phase
        preceded it."""
        if self._phase is WriterPolicyPhase.ABORTED:
            return ()
        return self._active_contracts

    def authorize_exact_mission_route(
        self, mission_route_contract: RouteContract, *, expected_route: str
    ) -> None:
        """May run exactly once, only from SEARCH_READ. Validates the ONE
        dynamically-constructed mission-open contract itself (it cannot
        have been validated anywhere else, since it did not exist before
        the mission id was resolved by search) before ever admitting it:
        host equals allowed_host, method GET, capability "read", the exact
        mission-open operation type, no body fields, no query fields, the
        exact canonical route derived from the validated positive integer
        mission id (checked against `expected_route`, computed by the
        caller from that same validated id), and not permanently blocked.
        """
        if self._phase is not WriterPolicyPhase.SEARCH_READ:
            raise PolicyPhaseError(
                f"authorize_exact_mission_route requires SEARCH_READ, current phase is {self._phase!r}"
            )
        c = mission_route_contract
        if c.host != self._allowed_host:
            raise ValueError("mission route contract host must equal allowed_host")
        if c.method != "GET":
            raise ValueError("mission route contract must be GET")
        if c.capability != "read":
            raise ValueError("mission route contract capability must be 'read'")
        if c.operation_type != MISSION_OPEN_OPERATION_TYPE:
            raise ValueError(
                f"mission route contract operation_type must be {MISSION_OPEN_OPERATION_TYPE!r}"
            )
        if c.body_fields:
            raise ValueError("mission route contract must not declare body fields")
        if c.query_fields:
            raise ValueError("mission route contract must not declare unexpected query fields")
        if c.route != expected_route:
            raise ValueError(
                "mission route contract route does not match the canonical route "
                "derived from the validated mission id"
            )
        if is_permanently_blocked(c.route):
            raise ValueError("mission route contract targets a permanently blocked route")
        self._active_contracts = self._active_contracts + (c,)
        self._phase = WriterPolicyPhase.MISSION_READ

    def activate_write_once(self) -> None:
        """May run exactly once, only from MISSION_READ. Takes no
        argument: it only exposes the write/native-recalc contract tuple
        that was validated and frozen at construction time, and cannot
        introduce anything new during activation. The caller (writer.py)
        is responsible for having already checked lease validity,
        identity agreement, workflow agreement, and (for PEC) row
        preflight BEFORE calling this -- this method performs no such
        check itself, it only performs the phase transition once those
        gates already passed."""
        if self._phase is not WriterPolicyPhase.MISSION_READ:
            raise PolicyPhaseError(
                f"activate_write_once requires MISSION_READ, current phase is {self._phase!r}"
            )
        self._active_contracts = self._active_contracts + self._frozen_write_contracts
        self._phase = WriterPolicyPhase.WRITE_ACTIVE

    def abort_deny_all(self) -> None:
        """From ANY phase, including ABORTED itself (idempotent no-op
        there): atomically denies everything. No `await` occurs between
        reading and setting `_phase`/`_active_contracts`, so no request
        handler running on the same event loop can observe a
        half-updated state."""
        self._phase = WriterPolicyPhase.ABORTED
        self._active_contracts = ()


class AbortOnlyHandle:
    """The ONLY object mcma.portal.writer.VerifiedMissionWriter is allowed
    to hold a reference to after construction completes. It exposes
    exactly one method -- there is no policy-mutation capability to
    "remember not to call": the object itself has no other method.
    authorize_exact_mission_route/activate_write_once are called only by
    the writer's own construction function, directly on the
    WriterPolicyController, before this handle is ever created."""

    __slots__ = ("_controller",)

    def __init__(self, controller: WriterPolicyController) -> None:
        self._controller = controller

    def abort(self) -> None:
        self._controller.abort_deny_all()


def _make_phased_route_handler(controller: WriterPolicyController, allowed_host: str):
    """Same fail-closed discipline as _make_route_handler, but reads the
    controller's current contract set fresh on every request instead of a
    closed-over sequence -- the mechanism that makes ABORTED deny
    everything immediately, including a request already in flight when
    abort_deny_all() was called (evaluated after the fact, it will see the
    now-empty contract set)."""

    async def handler(route: "Route") -> None:
        request = route.request
        try:
            canonical = _canonical_or_none(request)
            decision = evaluate_request(canonical, controller.contracts(), allowed_host)
        except Exception:
            await _abort_never_raising(route)
            return
        try:
            if decision is Decision.ALLOW:
                await route.continue_()
            else:
                await route.abort(_POLICY_DENY_ERROR)
        except Exception:
            await _abort_never_raising(route)

    return handler


async def install_phased_portal_guard(
    context: "BrowserContext",
    controller: WriterPolicyController,
    allowed_host: str,
) -> None:
    """Installs the phased route handler bound to an already-constructed
    WriterPolicyController. Mirrors install_portal_guard's own
    close-on-failure discipline. Internal to mcma.portal.writer's
    construction sequence -- not a general-purpose staged API."""
    try:
        await context.route("**/*", _make_phased_route_handler(controller, allowed_host))
        await context.route_web_socket("**/*", _deny_websocket)
    except Exception:
        await context.close()
        raise
