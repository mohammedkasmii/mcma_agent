"""The login context uses a deliberately different policy from the
agent's contract-based default-deny, because a human signing in needs the
portal's own login page to actually work -- its stylesheets, scripts,
redirects and OTP step cannot be enumerated as contracts in advance.

These tests pin what that difference is allowed to be. The widened policy
must still refuse every other host and every final endpoint; if it ever
stops doing either, that is a safety regression and these fail.
"""

import pytest

from mcma.portal.capabilities import portal_origin
from mcma.portal.final_endpoints import PERMANENTLY_BLOCKED_ENDPOINTS
from mcma.portal.interception import _make_login_route_handler

PORTAL = "sinauto.mamda-mcma.ma"


class _FakeRequest:
    def __init__(self, url, method="GET", content_type=None, post_data=None):
        self.url = url
        self.method = method
        self.post_data = post_data
        self._headers = {"content-type": content_type} if content_type else {}

    @property
    def headers(self):
        return self._headers


class _FakeRoute:
    def __init__(self, request):
        self.request = request
        self.continued = False
        self.aborted = False

    async def continue_(self):
        self.continued = True

    async def abort(self, _error=None):
        self.aborted = True


async def _decide(url, method="GET", host=PORTAL):
    handler = _make_login_route_handler(host)
    route = _FakeRoute(_FakeRequest(url, method))
    await handler(route)
    return route


def _run(coro):
    import asyncio

    return asyncio.run(coro)


# --------------------------------------------------------------------- #
# What the login flow needs
# --------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "path",
    [
        "/SinAuto_MCMA",
        "/SinAuto_MCMA/front/Login/login",
        "/SinAuto_MCMA/css/portal.css",
        "/SinAuto_MCMA/js/app.js",
        "/SinAuto_MCMA/images/logo.png",
        "/SinAuto_MCMA/expertise/otp",
    ],
)
def test_the_portals_own_login_flow_is_allowed(path):
    """None of these can be contracted in advance, and denying them is
    what left the employee looking at a blank window."""
    route = _run(_decide(f"https://{PORTAL}{path}"))
    assert route.continued is True
    assert route.aborted is False


def test_a_post_of_the_humans_credentials_is_allowed():
    """The human types them into the portal's own form; this application
    never sees, stores or submits them."""
    route = _run(_decide(f"https://{PORTAL}/SinAuto_MCMA/front/Login/login", method="POST"))
    assert route.continued is True


# --------------------------------------------------------------------- #
# What must stay blocked regardless
# --------------------------------------------------------------------- #


@pytest.mark.parametrize("blocked", PERMANENTLY_BLOCKED_ENDPOINTS)
def test_every_final_endpoint_stays_blocked_during_login(blocked):
    """Widening the policy for a login must never open a path to Valider,
    Cloture, Enregistrer or GED -- not even for a human driving this
    browser."""
    route = _run(_decide(f"https://{PORTAL}/SinAuto_MCMA/expertise/{blocked}", method="POST"))
    assert route.aborted is True
    assert route.continued is False


@pytest.mark.parametrize(
    "other_host",
    ["evil.example.com", "sinauto.mamda-mcma.ma.evil.com", "google.com", "127.0.0.1:9999"],
)
def test_every_other_host_is_denied(other_host):
    """One host only. Nothing can be fetched from, or leaked to, a third
    party during a login."""
    route = _run(_decide(f"https://{other_host}/anything"))
    assert route.aborted is True


def test_a_malformed_request_is_denied_not_allowed():
    route = _run(_decide("not-a-url-at-all"))
    assert route.aborted is True


# --------------------------------------------------------------------- #
# Scheme
# --------------------------------------------------------------------- #


def test_the_real_portal_is_reached_over_https():
    """The scheme was hardcoded to http, written when the only reachable
    host was the loopback mock. Pointed at the real portal that navigates
    to a URL it does not serve, so the window opened on about:blank and
    closed with no explanation."""
    assert portal_origin(PORTAL) == f"https://{PORTAL}"


@pytest.mark.parametrize("host", ["127.0.0.1:8080", "localhost:8080", "[::1]:8080"])
def test_the_loopback_mock_is_still_reached_over_http(host):
    assert portal_origin(host).startswith("http://")
