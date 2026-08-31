"""
mcma.portal.pilot_contracts -- the single-machine pilot's reviewed
RouteContract set (pilot-integration correction, sections 3/4/9).

Every route/method/field literal here mirrors mock_server.py's own routes
exactly (the same convention tests/portal/writer/writer_test_support.py
and tests/portal/capabilities/capabilities_test_support.py already
duplicate for their own fake-based unit tests -- "bounded duplication
over coupling to accepted files", the established INC-06/07/08/09
convention). This module is the ONE place the real job runner
(mcma.execution.runner) and the onboarding tool draw their reviewed
contracts from, so production wiring and the tests exercising the same
routes can never silently drift onto two different literal sets.

`_require_loopback_host` (mcma.portal.writer) already refuses any
non-loopback allowed_host before a browser context is ever created for a
writer; `pilot_allowed_host()` below is this module's own explicit
declaration of that same boundary for readers/onboarding -- the pilot
NEVER contacts the real SinAuto portal (every host here is loopback, and
this module has no live-host variant to switch to). A future increment
that reviews real SinAuto contracts would add a SEPARATE, explicitly
reviewed module -- it would never repurpose this one, which is
permanently mock-only by construction (see module name).
"""

from __future__ import annotations

from mcma.portal.contracts import RouteContract

# mock_server.py binds to 127.0.0.1:8080 in every test/pilot fixture in
# this repository; the pilot smoke command (docs/PILOT_SETUP.md) starts it
# on this exact host/port.
DEFAULT_PILOT_HOST = "127.0.0.1:8080"


def pilot_allowed_host(host: str = DEFAULT_PILOT_HOST) -> str:
    """Fails closed on anything that is not an explicit loopback host --
    the one gate this module offers before any contract below is ever
    handed to a browser-facing capability. This mirrors (never replaces)
    mcma.portal.writer's own internal loopback check."""
    from urllib.parse import urlsplit

    hostname = urlsplit(f"http://{host}").hostname
    if hostname not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError(f"pilot_contracts refuses a non-loopback host: {host!r}")
    return host


def _c(
    host: str,
    route: str,
    method: str,
    *,
    capability: str,
    operation_type: str,
    workflow: str | None = None,
    content_type: str | None = None,
    body_fields=(),
) -> RouteContract:
    return RouteContract(
        host=host,
        route=route,
        method=method,
        query_fields=frozenset(),
        content_type=content_type,
        body_fields=frozenset(body_fields),
        capability=capability,
        operation_type=operation_type,
        workflow=workflow,
    )


def auth_contracts(host: str) -> tuple[RouteContract, ...]:
    """For tools/onboarding_tool.py's open_login_session() only."""
    return (
        _c(host, "/SinAuto_MCMA/login", "GET", capability="auth", operation_type="login_page"),
    )


def read_contracts(host: str) -> tuple[RouteContract, ...]:
    """For mcma.portal.capabilities.open_reader() -- the real DRY_RUN
    read-only identity gate (section 3)."""
    return (
        _c(host, "/SinAuto_MCMA/expertise/frontexpert", "GET", capability="read", operation_type="search_page"),
        _c(
            host, "/SinAuto_MCMA/expertise/FrontExpert/listeMissions", "POST",
            capability="read", operation_type="search",
            content_type="application/x-www-form-urlencoded", body_fields={"Matricule", "ReferenceCie"},
        ),
        _c(
            host,
            "/SinAuto_MCMA/expertise/gestionExpert/getSinistre/idSinistre/612001/rubrique/gestionexpert-index",
            "GET",
            capability="read",
            operation_type="mission_page",
            workflow="MODE_NORMAL",
        ),
        _c(
            host,
            "/SinAuto_MCMA/expertise/gestionExpert/getSinistre/idSinistre/532805/rubrique/gestionexpert-index",
            "GET",
            capability="read",
            operation_type="mission_page",
            workflow="GARAGE_CONVENTIONNE",
        ),
    )


def write_contracts(host: str) -> tuple[RouteContract, ...]:
    """For open_verified_writer() -- both workflows' complete reviewed
    contract set (section 4). Includes each workflow's read_rows contract
    too (open_verified_writer requires exactly one read_rows match per
    workflow it is scoped to)."""
    return (
        _c(host, "/SinAuto_MCMA/expertise/frontexpert", "GET", capability="read", operation_type="search_page"),
        _c(
            host, "/SinAuto_MCMA/expertise/FrontExpert/listeMissions", "POST",
            capability="read", operation_type="search",
            content_type="application/x-www-form-urlencoded", body_fields={"Matricule", "ReferenceCie"},
        ),
        _c(
            host, "/SinAuto_MCMA/expertise/gestionExpert/listeRapportDefDet", "POST",
            capability="read", operation_type="read_rows", workflow="MODE_NORMAL",
            content_type="application/x-www-form-urlencoded",
        ),
        _c(
            host, "/SinAuto_MCMA/expertise/gestiongarage/listeDevisDet", "POST",
            capability="read", operation_type="read_rows", workflow="GARAGE_CONVENTIONNE",
            content_type="application/x-www-form-urlencoded",
        ),
        _c(
            host, "/SinAuto_MCMA/expertise/gestionExpert/createRapportDefDet", "POST",
            capability="row_write", operation_type="add_row", workflow="MODE_NORMAL",
            content_type="application/x-www-form-urlencoded",
            body_fields={"IdRubrique", "MontantHT", "Taxe", "MontantTTC", "TauxVetuste", "MontantVetuste", "TempRowId"},
        ),
        _c(
            host, "/SinAuto_MCMA/expertise/gestionexpert/updateDevisDet", "POST",
            capability="row_write", operation_type="edit_row", workflow="GARAGE_CONVENTIONNE",
            content_type="application/x-www-form-urlencoded",
            body_fields={
                "IdDevisDet", "MontantHTValide", "TaxeValide", "MontantTTCValide",
                "TauxVetusteValide", "MontantVetusteValide", "SubmissionNonce",
            },
        ),
        _c(
            host, "/_mock/pec/native_calculation", "POST",
            capability="native_recalc", operation_type="native_recalc", workflow="GARAGE_CONVENTIONNE",
            content_type="application/json",
            body_fields={"total_ttc", "total_tva", "franchise", "vetuste", "remise", "part_resp", "simulate"},
        ),
    )


# --------------------------------------------------------------------- #
# Notifications (section 8): NOT part of any default composition. Live
# SinAuto notification contracts are unreviewed -- this per-category
# contract shape exists only for the mock-only pilot poller/e2e proof,
# never wired into mcma.app.main's default production composition (which
# passes polling_configured=False and never constructs one of these).
# --------------------------------------------------------------------- #


def mock_only_notification_contract(host: str, code_alerte: str) -> RouteContract:
    from urllib.parse import quote

    route = f"/SinAuto_MCMA/expertise/notification/getAlerte/CodeAlerte/{quote(code_alerte, safe='')}"
    return _c(host, route, "POST", capability="read", operation_type="read_notifications")
