"""
INC-07 amendments #3/#4/#5/#7 -- the async Playwright adapter: one public
installer, correct await usage, ALLOW/DENY wiring, exception handling, and
the hardened context-options builder. All driven with hand-written stub
objects via asyncio.run() -- no real Playwright browser is launched.
"""

import pytest

from portal_test_support import (
    FailingHttpInstallContext,
    FailingWebSocketInstallContext,
    FakeContext,
    FakeRequest,
    FakeRequestHeadersRaise,
    FakeRoute,
    FakeWebSocketRoute,
    run_async,
)
from mcma.portal.contracts import RouteContract
from mcma.portal.interception import hardened_context_options, install_portal_guard

ALLOWED_HOST = "127.0.0.1:8080"

READ_CONTRACT = RouteContract(
    host=ALLOWED_HOST,
    route="/SinAuto_MCMA/expertise/gestionExpert/listeRapportDefDet",
    method="POST",
    query_fields=frozenset(),
    content_type="application/x-www-form-urlencoded",
    body_fields=frozenset(),
    capability="read",
    operation_type="list_rows",
    workflow=None,
)


# --------------------------------------------------------------------- #
# One safe public installer -- context-level, both HTTP and WS in one call
# --------------------------------------------------------------------- #


def test_install_portal_guard_registers_context_level_http_and_websocket_routes():
    context = FakeContext()
    run_async(install_portal_guard(context, (READ_CONTRACT,), ALLOWED_HOST))
    assert len(context.route_calls) == 1
    assert context.route_calls[0][0] == "**/*"
    assert len(context.ws_route_calls) == 1
    assert context.ws_route_calls[0][0] == "**/*"
    assert context.closed == 0


def test_installation_failure_on_http_route_closes_the_context():
    context = FailingHttpInstallContext()
    with pytest.raises(RuntimeError):
        run_async(install_portal_guard(context, (READ_CONTRACT,), ALLOWED_HOST))
    assert context.closed == 1


def test_installation_failure_on_websocket_route_closes_the_context():
    context = FailingWebSocketInstallContext()
    with pytest.raises(RuntimeError):
        run_async(install_portal_guard(context, (READ_CONTRACT,), ALLOWED_HOST))
    assert context.closed == 1
    # HTTP route did succeed before the failure, but the context must not
    # remain usable -- it is closed regardless of partial success.
    assert len(context.route_calls) == 1


# --------------------------------------------------------------------- #
# ALLOW / DENY wiring through the real handler the installer registers
# --------------------------------------------------------------------- #


def _installed_http_handler(contracts=(READ_CONTRACT,)):
    context = FakeContext()
    run_async(install_portal_guard(context, contracts, ALLOWED_HOST))
    return context.route_calls[0][1]


def test_allow_path_reaches_continue_exactly_once_never_abort_or_fulfill():
    handler = _installed_http_handler()
    request = FakeRequest(
        url=f"http://{ALLOWED_HOST}/SinAuto_MCMA/expertise/gestionExpert/listeRapportDefDet",
        method="POST",
        headers={"content-type": "application/x-www-form-urlencoded"},
        post_data="",
    )
    route = FakeRoute(request)
    run_async(handler(route))
    assert route.continued == 1
    assert route.aborted == 0
    assert route.fulfilled == 0


def test_deny_path_aborts_exactly_once_never_continue_or_fulfill():
    handler = _installed_http_handler()
    request = FakeRequest(
        url=f"http://{ALLOWED_HOST}/SinAuto_MCMA/expertise/gestionExpert/unknownRoute",
        method="GET",
    )
    route = FakeRoute(request)
    run_async(handler(route))
    assert route.aborted == 1
    assert route.continued == 0
    assert route.fulfilled == 0


def test_descriptor_extraction_failure_aborts():
    handler = _installed_http_handler()
    route = FakeRoute(FakeRequestHeadersRaise())
    run_async(handler(route))
    assert route.aborted == 1
    assert route.continued == 0


def test_handler_failure_never_falls_through():
    """A broken policy (not iterable) must still result in abort, never a
    silent continue -- the handler's own try/except is the safety net, not
    caller discipline."""
    context = FakeContext()
    run_async(install_portal_guard(context, (READ_CONTRACT,), ALLOWED_HOST))
    handler = context.route_calls[0][1]
    request = FakeRequest(url=f"http://{ALLOWED_HOST}/x", method="GET")
    route = FakeRoute(request)

    # Monkeypatch the route's own policy reference indirectly is not
    # possible from outside; instead prove the guarantee by constructing a
    # handler over a policy that raises when iterated.
    from mcma.portal.interception import _make_route_handler

    class ExplodingContracts:
        def __iter__(self):
            raise RuntimeError("policy blew up")

    broken_handler = _make_route_handler(ExplodingContracts(), ALLOWED_HOST)
    run_async(broken_handler(route))
    assert route.aborted == 1
    assert route.continued == 0


def test_blocked_request_never_receives_fake_success():
    handler = _installed_http_handler()
    request = FakeRequest(
        url=f"http://{ALLOWED_HOST}/SinAuto_MCMA/expertise/gestiongarage/garageModifierValDevis",
        method="POST",
        headers={"content-type": "application/x-www-form-urlencoded"},
        post_data="",
    )
    route = FakeRoute(request)
    run_async(handler(route))
    assert route.fulfilled == 0
    assert route.aborted == 1


# --------------------------------------------------------------------- #
# WebSocket denial
# --------------------------------------------------------------------- #


def test_websocket_route_is_closed_never_allowed():
    context = FakeContext()
    run_async(install_portal_guard(context, (READ_CONTRACT,), ALLOWED_HOST))
    ws_handler = context.ws_route_calls[0][1]
    ws_route = FakeWebSocketRoute()
    run_async(ws_handler(ws_route))
    assert ws_route.closed == 1


# --------------------------------------------------------------------- #
# Hardened context options -- service_workers cannot be overridden
# --------------------------------------------------------------------- #


def test_hardened_context_options_forces_block_when_absent():
    options = hardened_context_options({})
    assert options["service_workers"] == "block"


def test_hardened_context_options_accepts_explicit_block():
    options = hardened_context_options({"service_workers": "block", "headless": True})
    assert options["service_workers"] == "block"
    assert options["headless"] is True


def test_hardened_context_options_rejects_conflicting_override():
    with pytest.raises(ValueError):
        hardened_context_options({"service_workers": "allow"})
