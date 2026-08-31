"""
mcma.portal.sinauto_contracts -- the reviewed RouteContract set for the
REAL SinAuto portal.

mcma.portal.pilot_contracts is permanently mock-only by construction: its
pilot_allowed_host() refuses any non-loopback host, so nothing drawing
its contracts from there can ever reach sinauto.mamda-mcma.ma. Its own
module docstring says the successor "would add a SEPARATE, explicitly
reviewed module -- it would never repurpose this one". This is that
module.

READ AND LOGIN ONLY. There is deliberately no write_contracts() here.

That omission is the point, not an oversight. RELEASE_GATES.md G5 makes
INC-23 the only increment that may permit a live row write, gated on
confirmed row-op contract records and explicit owner approval, and
mcma.portal.writer._require_loopback_host independently refuses a
non-loopback host before a writer's browser context is ever created. So
a live write remains impossible whether or not this module exists, and
adding write routes here would neither enable one nor be safe: the exact
Mode Normal native-trigger contract is recorded UNCONFIRMED
(PORTAL_ROW_WORKFLOWS.md §3.1). Reading notifications and letting a human
log in carry none of that risk -- neither can alter a claim.

Every route below is transcribed from PORTAL_CONTRACT.md, which recovered
them from the working baseline, and each is annotated with its source.
Nothing here is inferred from a URL that merely looked plausible.
"""

from __future__ import annotations

from urllib.parse import quote, urlsplit

from mcma.portal.contracts import RouteContract

# The production portal. Both entities (MCMA and MAMDA) and both scopes
# (Oujda and Nador) are reached through this ONE host -- they are portal
# ACCOUNTS, not separate deployments (FEATURE_INVENTORY.md's resolved
# requirement: "Oujda/Nador are account profiles/notification scopes from
# one office, not city deployments").
DEFAULT_SINAUTO_HOST = "sinauto.mamda-mcma.ma"


class UnreviewedHost(ValueError):
    """A host other than the reviewed SinAuto host (or an explicit
    loopback host for local testing) was requested."""


def sinauto_allowed_host(host: str = DEFAULT_SINAUTO_HOST) -> str:
    """Fails closed on any host that is neither the reviewed production
    portal nor an explicit loopback address.

    Loopback is permitted so the same composition can be pointed at
    mock_server.py without swapping contract modules -- the mock serves
    these identical routes. It is NOT a way to reach some third host: an
    arbitrary hostname is refused here, before a browser context is ever
    created for it."""
    hostname = urlsplit(f"http://{host}").hostname
    if hostname is None:
        raise UnreviewedHost(f"not a parseable host: {host!r}")
    if hostname == DEFAULT_SINAUTO_HOST:
        return host
    if hostname in ("127.0.0.1", "::1"):
        return host
    raise UnreviewedHost(
        f"sinauto_contracts refuses an unreviewed host: {host!r} "
        f"(expected {DEFAULT_SINAUTO_HOST} or an explicit loopback address)"
    )


def _c(host, route, method, *, capability, operation_type, content_type=None, body_fields=()):
    return RouteContract(
        host=host,
        route=route,
        method=method,
        query_fields=frozenset(),
        content_type=content_type,
        body_fields=frozenset(body_fields),
        capability=capability,
        operation_type=operation_type,
        workflow=None,
    )


def auth_contracts(host: str = DEFAULT_SINAUTO_HOST) -> tuple[RouteContract, ...]:
    """For open_login_session() -- the human performs the login and OTP
    themselves in a visible browser. LoginCapability navigates only to
    the single GET route below and polls fixed logged-in markers; it
    never accepts a credential, never fills a form, and never opens a
    mission page (SAFETY_MODEL.md §1).

    Source: PORTAL_CONTRACT.md -- the baseline navigates
    sinauto.mamda-mcma.ma/SinAuto_MCMA/ for manual login."""
    host = sinauto_allowed_host(host)
    return (
        _c(host, "/SinAuto_MCMA", "GET", capability="auth", operation_type="login_page"),
    )


def notification_contracts(host: str, category_codes) -> tuple[RouteContract, ...]:
    """One contract per alert category, plus the same-origin landing page
    a reader must navigate to before any fetch-based read runs.

    Category-scoped by design: a reader may fetch a category only if a
    reviewed contract for that exact code was installed, so the set of
    categories a poll can reach is fixed by the caller, never widened by
    the portal's own response.

    Source: PORTAL_CONTRACT.md §7 -- POST .../notification/getAlerte/
    CodeAlerte/{code} with DataTables length=-1/iDisplayLength=-1, which
    asks for the complete dataset rather than a page (the poll-run
    lifecycle needs completeness evidence, not a first page)."""
    host = sinauto_allowed_host(host)
    contracts = [
        # A same-origin document must exist before fetch-based reads run.
        _c(host, "/SinAuto_MCMA/expertise/frontexpert", "GET",
           capability="read", operation_type="search_page"),
    ]
    for code in category_codes:
        contracts.append(
            _c(
                host,
                f"/SinAuto_MCMA/expertise/notification/getAlerte/CodeAlerte/{quote(str(code), safe='')}",
                "POST",
                capability="read",
                operation_type="read_notifications",
            )
        )
    return tuple(contracts)
