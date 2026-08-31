"""Category discovery against a REALISTIC portal page: one where
FrontExpert arrives with an empty navbar and the categories exist only in
the alert-list fragment that a separate read returns.

This is the shape the baseline actually dealt with -- it refreshed the
navbar before parsing category links -- and it is the case the first Phase
B implementation would have failed: the discovery context held only the
landing-page contract, so the alert-list request was denied by its own
guard and a healthy authenticated account reported NO_CATEGORIES.

The guard is REAL here (evaluate_request against the same contracts
production uses); only the page is faked.
"""

import asyncio

import pytest

from mcma.portal.capabilities import ReadCapability
from mcma.portal.contracts import Decision, evaluate_request
from mcma.portal.final_endpoints import PERMANENTLY_BLOCKED_ENDPOINTS
from mcma.portal.sinauto_contracts import (
    DEFAULT_SINAUTO_HOST,
    category_discovery_contracts,
    notification_contracts,
    portal_base_for,
)

# A realistic fragment: the categories live ONLY here, never on the
# landing page. Includes hostile entries that must not survive.
ALERT_LIST_FRAGMENT = """
<ul id="listeAlertes">
  <li><a href="/SinAuto_MCMA/expertise/notification/alerte/MISSIONS">
        Missions <span class="badge">10</span></a></li>
  <li><a href="/SinAuto_MCMA/expertise/notification/alerte/RELANCES-EXPERT">
        Relances <span class="badge">2</span></a></li>
  <li><a href="/SinAuto_MCMA/expertise/notification/alerte/MISSIONS">Duplicate</a></li>
  <li><a href="https://evil.example.com/expertise/notification/alerte/STEAL">Hostile host</a></li>
  <li><a href="https://evil.example.com/SinAuto_MCMA/expertise/notification/alerte/LOOKALIKE">
        Hostile host carrying the legitimate path</a></li>
  <li><a href="/SinAuto_MCMA/expertise/notification/alerte/../../gestionExpert/expertEnregistrerMission">
        Traversal</a></li>
</ul>
"""


class GuardedPage:
    """Evaluates every request through the REAL guard, so a route with no
    contract is denied exactly as it would be in production."""

    def __init__(self, contracts, host, *, fragment=ALERT_LIST_FRAGMENT, landing_links=(), entity="MCMA"):
        self._contracts = tuple(contracts)
        self._host = host
        self._entity = entity
        self._fragment = fragment
        self._landing_links = tuple(landing_links)
        self.allowed_requests = []
        self.denied_requests = []

    def _decide(self, url, method):
        from mcma.portal.canonical import canonicalize_request

        canonical = canonicalize_request(
            raw_url=url, raw_method=method, raw_content_type=None, raw_body=None
        )
        decision = evaluate_request(canonical, self._contracts, self._host)
        (self.allowed_requests if decision is Decision.ALLOW else self.denied_requests).append(
            (method, canonical.path)
        )
        return decision is Decision.ALLOW

    async def evaluate(self, script, arg=None):
        # The alert-list read: allowed only if a contract permits it.
        if "DOMParser" in script:
            url = arg[0] if isinstance(arg, (list, tuple)) else arg
            if not self._decide(url, "GET"):
                return None          # what a blocked fetch produces
            return _codes_from(self._fragment, f"{portal_base_for(self._entity)}/expertise/notification/alerte")
        # The live-page read: no request, just whatever the navbar holds.
        return list(self._landing_links)  # arg is the base prefix; no request is made


PORTAL_ORIGIN = f"https://{DEFAULT_SINAUTO_HOST}"


def _codes_from(html, prefix="/SinAuto_MCMA/expertise/notification/alerte"):
    """Mirrors the in-page extraction exactly: the href is RESOLVED
    against the current origin, and only a same-origin link whose path
    starts with this application's notification prefix contributes a
    code. A substring test would let an absolute hostile URL containing
    the same path through."""
    import re
    from urllib.parse import urljoin, urlsplit

    codes = []
    for href in re.findall(r'href="([^"]*)"', html):
        resolved = urljoin(f"{PORTAL_ORIGIN}/SinAuto_MCMA/expertise/frontexpert", href)
        parts = urlsplit(resolved)
        if f"{parts.scheme}://{parts.netloc}" != PORTAL_ORIGIN:
            continue
        if not parts.path.startswith(prefix + "/"):
            continue
        match = re.search(r"alerte/([A-Za-z0-9-]+)$", parts.path)
        if match:
            codes.append(match.group(1))
    return codes


def _reader(entity="MCMA", **kwargs):
    contracts = category_discovery_contracts(DEFAULT_SINAUTO_HOST, entity)
    page = GuardedPage(contracts, DEFAULT_SINAUTO_HOST, entity=entity, **kwargs)
    return ReadCapability(object(), page, DEFAULT_SINAUTO_HOST, portal_base_for(entity)), page


def _run(coro):
    return asyncio.run(coro)


# --------------------------------------------------------------------- #
# The bug this fixes
# --------------------------------------------------------------------- #


def test_categories_are_found_even_though_the_landing_page_has_none():
    """The whole point: FrontExpert is empty, and discovery still works
    because it performs the alert-list read itself."""
    reader, page = _reader(landing_links=())
    codes = _run(reader.discover_notification_categories())

    assert codes == ("MISSIONS", "RELANCES-EXPERT")
    assert ("GET", "/SinAuto_MCMA/expertise/notification/alerte") in page.allowed_requests
    assert page.denied_requests == []


def test_the_pre_fix_contract_set_would_have_found_nothing():
    """Negative control. With ONLY the landing-page contract -- the Phase
    B state -- the guard denies the alert-list read and this realistic
    page yields no categories at all. That is the NO_CATEGORIES an
    authenticated account would have seen."""
    landing_only = tuple(
        c for c in category_discovery_contracts(DEFAULT_SINAUTO_HOST, "MCMA")
        if c.operation_type != "notification_categories"
    )
    page = GuardedPage(landing_only, DEFAULT_SINAUTO_HOST, landing_links=())
    reader = ReadCapability(object(), page, DEFAULT_SINAUTO_HOST, "/SinAuto_MCMA")

    assert _run(reader.discover_notification_categories()) == ()
    assert page.denied_requests == [("GET", "/SinAuto_MCMA/expertise/notification/alerte")]


def test_a_portal_that_populated_its_own_navbar_still_works():
    """Some pages fill #listeAlertes themselves. Reading the live DOM as
    well costs no request and cannot introduce a route."""
    reader, page = _reader(fragment="<ul></ul>", landing_links=["MISSIONS", "RELANCES"])
    assert _run(reader.discover_notification_categories()) == ("MISSIONS", "RELANCES")


# --------------------------------------------------------------------- #
# What discovery still cannot do
# --------------------------------------------------------------------- #


@pytest.mark.parametrize("entity", ["MCMA", "MAMDA"])
def test_the_discovery_context_cannot_fetch_a_category_it_finds(entity):
    """Two contexts exist precisely so this stays true: discovery can
    populate and read the list, and cannot read any category in it."""
    from mcma.portal.canonical import canonicalize_request

    contracts = category_discovery_contracts(DEFAULT_SINAUTO_HOST, entity)
    base = portal_base_for(entity)
    blocked = canonicalize_request(
        raw_url=f"https://{DEFAULT_SINAUTO_HOST}{base}"
                "/expertise/notification/getAlerte/CodeAlerte/MISSIONS",
        raw_method="POST", raw_content_type=None, raw_body=None,
    )
    assert evaluate_request(blocked, contracts, DEFAULT_SINAUTO_HOST) is Decision.DENY


def test_hostile_hrefs_and_codes_never_survive():
    """A hostile host, a traversal attempt and a duplicate are all in the
    fragment above; only the two real codes come out."""
    reader, page = _reader()
    codes = _run(reader.discover_notification_categories())
    assert codes == ("MISSIONS", "RELANCES-EXPERT")
    # Including the lookalike: an absolute URL on another host that
    # carries the legitimate path would pass a substring test.
    assert "LOOKALIKE" not in codes
    assert "STEAL" not in codes
    assert not any("evil" in c or ".." in c or "/" in c for c in codes)


def test_a_blocked_or_broken_read_is_no_categories_not_a_crash():
    """The fetch script swallows its own failure into None, so a denied
    read is simply "no codes from this source"."""
    reader, page = _reader(fragment="")
    assert _run(reader.discover_notification_categories()) == ()


@pytest.mark.parametrize("entity,base", [("MCMA", "/SinAuto_MCMA"), ("MAMDA", "/SinAuto_MAMDA")])
def test_each_entity_reads_its_own_alert_list(entity, base):
    reader, page = _reader(entity=entity)
    _run(reader.discover_notification_categories())
    assert ("GET", f"{base}/expertise/notification/alerte") in page.allowed_requests
    # And never the other entity's.
    other = "/SinAuto_MAMDA" if entity == "MCMA" else "/SinAuto_MCMA"
    assert not any(path.startswith(other) for _, path in page.allowed_requests)


def test_no_final_endpoint_is_reachable_from_the_discovery_context():
    from mcma.portal.canonical import canonicalize_request

    contracts = category_discovery_contracts(DEFAULT_SINAUTO_HOST, "MCMA")
    for blocked in PERMANENTLY_BLOCKED_ENDPOINTS:
        canonical = canonicalize_request(
            raw_url=f"https://{DEFAULT_SINAUTO_HOST}/SinAuto_MCMA/expertise/{blocked}",
            raw_method="POST", raw_content_type=None, raw_body=None,
        )
        assert evaluate_request(canonical, contracts, DEFAULT_SINAUTO_HOST) is Decision.DENY


def test_the_fetch_context_is_the_only_one_that_can_read_categories():
    from mcma.portal.canonical import canonicalize_request

    fetch_contracts = notification_contracts(DEFAULT_SINAUTO_HOST, ["MISSIONS"], "MCMA")
    canonical = canonicalize_request(
        raw_url=f"https://{DEFAULT_SINAUTO_HOST}"
                "/SinAuto_MCMA/expertise/notification/getAlerte/CodeAlerte/MISSIONS",
        raw_method="POST", raw_content_type=None, raw_body=None,
    )
    assert evaluate_request(canonical, fetch_contracts, DEFAULT_SINAUTO_HOST) is Decision.ALLOW


@pytest.mark.skip(reason="REAL_NOTIFICATION_DISCOVERY_PENDING_ONSITE: needs an authenticated portal session")
def test_REAL_NOTIFICATION_DISCOVERY_PENDING_ONSITE():
    """Deferred onsite verification for Phase B, recorded here so it shows
    up in every run rather than living in a chat message.

    With a real authenticated session, for MCMA and MAMDA both:

      1. GET {base}/expertise/notification/alerte returns the alert-list
         fragment. The PATH is recovered verbatim from the baseline; the
         METHOD is inferred from jQuery .load(url) issuing a GET, and is
         the single unobserved assumption in this path -- check it first
         if discovery returns nothing.
      2. #listeAlertes links carry real category codes matching
         [A-Za-z0-9-]+
      3. discover_notification_categories() returns those codes
      4. each code fetches rows through getAlerte/CodeAlerte/{code}
      5. rows normalise into claims under the correct account
      6. the dashboard shows them for that account only

    If step 1 returns nothing, capture the real alert-list markup and the
    request the portal itself issues; do not guess another method or path."""
