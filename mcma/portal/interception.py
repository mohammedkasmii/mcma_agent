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

import traceback
from typing import TYPE_CHECKING, Sequence

from mcma.portal.canonical import canonicalize_request
from mcma.portal.contracts import Decision, RouteContract, evaluate_request

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
        # --- TEMPORARY CI-ONLY DIAGNOSTICS (investigating CI runs
        # 33316988633/33317487676; kept for one more run per review
        # sequencing, to observe a real-browser ALLOW+continue_() succeed for
        # the first time in this project). Remove once CI confirms green.
        print(
            f"[DIAG intercept] url={request.url!r} method={request.method!r} "
            f"resource_type={getattr(request, 'resource_type', None)!r}"
        )
        try:
            canonical = _canonical_or_none(request)
            decision = evaluate_request(canonical, contracts, allowed_host)
        except Exception:
            print(f"[DIAG intercept] EXCEPTION during descriptor/decision for {request.url!r}:")
            traceback.print_exc()
            await _abort_never_raising(route, request)
            return
        print(f"[DIAG intercept] canonical={canonical!r} decision={decision!r} url={request.url!r}")
        # --- END TEMPORARY DIAGNOSTICS (the try/except below is the actual
        # fix, not diagnostic-only; see mcma.portal.interception module docs) ---
        try:
            if decision is Decision.ALLOW:
                await route.continue_()
                print(f"[DIAG intercept] continue_() returned normally for {request.url!r}")
            else:
                await route.abort(_POLICY_DENY_ERROR)
                print(f"[DIAG intercept] abort() returned normally for {request.url!r}")
        except Exception:
            print(f"[DIAG intercept] continue_()/abort() RAISED for {request.url!r} decision={decision!r}:")
            traceback.print_exc()
            await _abort_never_raising(route, request)

    return handler


async def _abort_never_raising(route: "Route", request) -> None:
    """Best-effort fail-closed abort that itself never raises: whatever
    already went wrong, the handler coroutine must still return normally
    rather than let an exception escape (an escaped exception is exactly
    what produces the ambiguous, un-attributable net::ERR_FAILED this
    function exists to prevent)."""
    try:
        await route.abort(_POLICY_DENY_ERROR)
    except Exception:
        print(f"[DIAG intercept] fallback abort() ALSO RAISED for {request.url!r}:")
        traceback.print_exc()


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
