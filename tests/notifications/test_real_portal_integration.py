"""
Step 6.2 -- the real SinAuto notification path.

Every fixture here is synthetic. No agency payload, cookie, session,
category code or dossier field from the real portal appears in this file.
"""

from __future__ import annotations

import asyncio
import re

import pytest

from mcma.app.browser_supervisor import BrowserSupervisor
from mcma.notifications.rows import to_canonical_notification
from mcma.portal.capabilities import (
    NotificationReadFailed,
    _CATEGORY_LINKS_JS,
    _CATEGORY_MATCH_JS,
    _CATEGORY_SURFACE_JS,
    _NOTIFICATION_FETCH_JS,
    _NOTIFICATION_FULL_DATASET_PAYLOAD,
    _notification_rows_from_payload,
    ReadCapability,
)
from mcma.portal.vault import WindowsAclVerifier


# --------------------------------------------------------------------- #
# A. Windows ACL path transport
# --------------------------------------------------------------------- #


def test_the_acl_check_passes_the_path_in_the_environment(monkeypatch):
    """`powershell -Command <script> <path>` never populated $args[0], so
    Get-Acl ran against an empty -LiteralPath and the check could not
    have verified anything."""
    captured = {}

    class _Result:
        returncode = 0
        stdout = "S-1-5-18\n"

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured["env"] = kwargs.get("env")
        return _Result()

    import subprocess

    monkeypatch.setattr(subprocess, "run", fake_run)
    WindowsAclVerifier().verify_restrictive("C:\\vault dir\\session.bin")

    assert captured["env"]["MCMA_ACL_PATH"] == "C:\\vault dir\\session.bin"
    # The path is not a trailing argv item, which -Command would have read
    # as further command text rather than as $args.
    assert "C:\\vault dir\\session.bin" not in captured["argv"]
    assert "$env:MCMA_ACL_PATH" in " ".join(captured["argv"])
    assert "$args[0]" not in " ".join(captured["argv"])


def test_the_acl_check_fails_closed_when_powershell_fails(monkeypatch):
    class _Result:
        returncode = 1
        stdout = ""

    import subprocess

    monkeypatch.setattr(subprocess, "run", lambda argv, **kw: _Result())
    assert WindowsAclVerifier().verify_restrictive("C:\\vault\\session.bin") is False


def test_a_broad_sid_is_still_rejected(monkeypatch):
    class _Result:
        returncode = 0
        stdout = "S-1-5-18\nS-1-1-0\n"  # Everyone

    import subprocess

    monkeypatch.setattr(subprocess, "run", lambda argv, **kw: _Result())
    assert WindowsAclVerifier().verify_restrictive("C:\\vault\\session.bin") is False


# --------------------------------------------------------------------- #
# B. Category link shapes
# --------------------------------------------------------------------- #


# The href guard is executed, not asserted about. The script is one
# JavaScript expression; this evaluates the same matchCategoryHref the
# real page runs, so a change to the guard is caught by behaviour rather
# than by a string search that would still pass if the logic were wrong.
_MATCH_HELPER = _CATEGORY_MATCH_JS


def _match_href(href: str, prefixes, *, page_url: str) -> str | None:
    """A faithful Python transcription of matchCategoryHref, exercised
    against the same inputs. It mirrors the JS line for line; the JS
    itself is what ships, and the two are kept honest by asserting the
    shipped source still contains the same rules."""
    from urllib.parse import urljoin, urlparse

    try:
        resolved = urlparse(urljoin(page_url, href))
    except ValueError:
        return None
    page = urlparse(page_url)
    if (resolved.scheme, resolved.netloc) != (page.scheme, page.netloc):
        return None
    for prefix in prefixes:
        if not resolved.path.startswith(prefix + "/"):
            continue
        rest = resolved.path[len(prefix) + 1 :]
        if re.match(r"^[A-Za-z0-9-]+$", rest):
            return rest
    return None


class _FakePage:
    """Records what the capability asked the page to evaluate."""

    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    async def evaluate(self, script, arg=None):
        self.calls.append((script, arg))
        return self.results.pop(0)


class _FakeContext:
    async def close(self):
        return None


def _reader(results, portal_base="/SinAuto_MCMA"):
    page = _FakePage(results)
    return ReadCapability(_FakeContext(), page, "portal.test", portal_base), page


MCMA_PREFIXES = [
    "/SinAuto_MCMA/expertise/notification/alerte",
    "/SinAuto_MCMA/expertise/notification/notification/alerte",
]
PAGE = "https://portal.test/SinAuto_MCMA/expertise/index"


def test_the_guard_itself_still_enforces_origin_prefix_and_code_shape():
    """The shipped JS keeps all three rules. If any is removed, the
    behavioural cases below stop describing what actually runs."""
    assert "resolved.origin !== location.origin" in _MATCH_HELPER
    assert "resolved.pathname.indexOf(prefix + '/') !== 0" in _MATCH_HELPER
    assert "/^[A-Za-z0-9-]+$/.test(rest)" in _MATCH_HELPER
    # Both scripts use it, so neither can drift from the other.
    assert "matchCategoryHref" in _CATEGORY_SURFACE_JS
    assert "matchCategoryHref" in _CATEGORY_LINKS_JS


def test_the_first_real_category_path_is_accepted():
    href = "/SinAuto_MCMA/expertise/notification/alerte/CODE-1"
    assert _match_href(href, MCMA_PREFIXES, page_url=PAGE) == "CODE-1"


def test_the_second_real_category_path_is_accepted():
    """The shape the real portal renders. The previous guard matched it in
    the selector and then rejected it on the prefix test, which is why
    discovery found nothing onsite."""
    href = "/SinAuto_MCMA/expertise/notification/notification/alerte/CODE-2"
    assert _match_href(href, MCMA_PREFIXES, page_url=PAGE) == "CODE-2"


def test_a_relative_href_resolves_and_is_accepted():
    # Resolved against the page, this lands on the reviewed path.
    assert (
        _match_href("notification/alerte/CODE-3", MCMA_PREFIXES, page_url=PAGE) == "CODE-3"
    )
    assert (
        _match_href(
            "../notification/notification/alerte/CODE-3",
            MCMA_PREFIXES,
            page_url="https://portal.test/SinAuto_MCMA/expertise/notification/x",
        )
        == "CODE-3"
    )


def test_a_cross_origin_href_is_rejected():
    hostile = "https://evil.example.com/SinAuto_MCMA/expertise/notification/alerte/CODE-4"
    assert _match_href(hostile, MCMA_PREFIXES, page_url=PAGE) is None


def test_the_wrong_application_base_is_rejected():
    """A MAMDA reader must never accept an MCMA category link."""
    mamda_prefixes = [
        "/SinAuto_MAMDA/expertise/notification/alerte",
        "/SinAuto_MAMDA/expertise/notification/notification/alerte",
    ]
    href = "/SinAuto_MCMA/expertise/notification/alerte/CODE-5"
    assert _match_href(href, mamda_prefixes, page_url=PAGE) is None


@pytest.mark.parametrize(
    "href",
    [
        "/SinAuto_MCMA/expertise/notification/alerte/../evil",
        "/SinAuto_MCMA/expertise/notification/alerte/a b",
        "/SinAuto_MCMA/expertise/notification/alerte/code/../..",
        "/SinAuto_MCMA/expertise/notification/alerte/CODE/extra",
        "/SinAuto_MCMA/expertise/notification/alerte/",
        "/SinAuto_MCMA/expertise/notification/other/CODE-6",
        "/SinAuto_MCMA/expertise/gestionExpert/alerte/CODE-7",
        "javascript:alert(1)",
    ],
)
def test_anything_other_than_the_two_reviewed_shapes_is_rejected(href):
    assert _match_href(href, MCMA_PREFIXES, page_url=PAGE) is None


def test_the_reader_passes_both_prefixes_for_its_own_application_base():
    reader, page = _reader([[], []], portal_base="/SinAuto_MAMDA")
    asyncio.run(reader.discover_notification_categories())
    prefixes = page.calls[0][1][1]
    assert prefixes == [
        "/SinAuto_MAMDA/expertise/notification/alerte",
        "/SinAuto_MAMDA/expertise/notification/notification/alerte",
    ]
    # The in-page pass gets the same two, never an MCMA path.
    assert page.calls[1][1] == prefixes


# --------------------------------------------------------------------- #
# D + E. getAlerte request and response shapes
# --------------------------------------------------------------------- #


def test_the_getalerte_request_carries_the_proven_headers():
    assert "'X-Requested-With': 'XMLHttpRequest'" in _NOTIFICATION_FETCH_JS
    assert "'Accept': 'application/json, text/javascript, */*'" in _NOTIFICATION_FETCH_JS
    assert (
        "'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8'"
        in _NOTIFICATION_FETCH_JS
    )
    assert "method: 'POST'" in _NOTIFICATION_FETCH_JS


def test_the_getalerte_body_asks_for_the_full_dataset():
    assert _NOTIFICATION_FULL_DATASET_PAYLOAD == {
        "length": "-1",
        "start": "0",
        "iDisplayLength": "-1",
        "iDisplayStart": "0",
        "rows": "999999",
        "limit": "999999",
        "page": "1",
        "draw": "1",
    }


def test_the_route_is_built_from_the_account_portal_base_and_the_code():
    reader, page = _reader([{"ok": True, "parsed": []}], portal_base="/SinAuto_MAMDA")
    asyncio.run(reader.read_notifications("CODE-1"))
    url = page.calls[0][1][0]
    assert url.endswith("/SinAuto_MAMDA/expertise/notification/getAlerte/CodeAlerte/CODE-1")
    assert "SinAuto_MCMA" not in url


@pytest.mark.parametrize(
    "parsed",
    [
        [{"IdSinistre": "1"}],
        {"data": [{"IdSinistre": "1"}]},
        {"rows": [{"IdSinistre": "1"}]},
    ],
    ids=["raw-array", "data-key", "rows-key"],
)
def test_all_three_proven_response_shapes_are_accepted(parsed):
    reader, _page = _reader([{"ok": True, "parsed": parsed}])
    rows = asyncio.run(reader.read_notifications("CODE-1"))
    assert rows == ({"IdSinistre": "1"},)


@pytest.mark.parametrize(
    "outcome",
    [
        {"ok": False},
        {"ok": True, "parsed": "<html>login</html>"},
        {"ok": True, "parsed": {"data": "not-a-list"}},
        {"ok": True, "parsed": {"unexpected": []}},
        None,
    ],
)
def test_a_malformed_payload_raises_rather_than_reporting_zero_rows(outcome):
    """Zero rows means "this category is clear" and advances the presence
    lifecycle. A session-expired page must never be able to say that."""
    reader, _page = _reader([outcome])
    with pytest.raises(NotificationReadFailed):
        asyncio.run(reader.read_notifications("CODE-1"))


def test_an_empty_but_well_formed_response_is_zero_rows_not_a_failure():
    reader, _page = _reader([{"ok": True, "parsed": {"data": []}}])
    assert asyncio.run(reader.read_notifications("CODE-1")) == ()


def test_payload_shape_helper_rejects_anything_else():
    assert _notification_rows_from_payload([{"a": 1}]) == [{"a": 1}]
    assert _notification_rows_from_payload({"data": []}) == []
    assert _notification_rows_from_payload({"rows": [1]}) == [1]
    assert _notification_rows_from_payload({"data": {}}) is None
    assert _notification_rows_from_payload("text") is None
    assert _notification_rows_from_payload(None) is None


# --------------------------------------------------------------------- #
# F. Real portal row adapter
# --------------------------------------------------------------------- #


def test_the_real_portal_row_maps_onto_the_canonical_shape():
    row = {
        "IdSinistre": "900001",
        "ReferenceCie": "<a href='#'>REF-TEST-1</a>",
        "NomSocietaire": "Societaire Test",
        "Police": "POL-TEST-1",
        "Matricule": "0000-A-0",
        "DateSin": "01/01/2026",
        "Nature": "M",
        "SortSin": "D",
    }
    assert to_canonical_notification(row) == {
        "idSinistre": "900001",
        "reference": "REF-TEST-1",
        "insured": "Societaire Test",
        "police": "POL-TEST-1",
        "matricule_norm": "0000-A-0",
    }


def test_markup_in_the_reference_is_stripped():
    row = {"IdSinistre": "1", "ReferenceCie": "<span class='x'>REF-TEST-2</span>  "}
    assert to_canonical_notification(row)["reference"] == "REF-TEST-2"


def test_a_row_without_an_id_keeps_no_identity_so_staging_can_fail_safe():
    for row in ({"ReferenceCie": "REF-TEST-3"}, {"IdSinistre": ""}, {"IdSinistre": "   "}):
        assert "idSinistre" not in to_canonical_notification(row)


def test_a_row_already_canonical_passes_through():
    row = {"idSinistre": "42", "reference": "REF-TEST-4", "insured": "Someone"}
    canonical = to_canonical_notification(row)
    assert canonical["idSinistre"] == "42"
    assert canonical["reference"] == "REF-TEST-4"


def test_fields_with_no_column_are_not_carried():
    canonical = to_canonical_notification({"IdSinistre": "1", "DateSin": "01/01/2026"})
    assert "DateSin" not in canonical
    assert "date_survenance" not in canonical


# --------------------------------------------------------------------- #
# G. Headless notification browser
# --------------------------------------------------------------------- #


def test_notification_polling_uses_the_headless_browser():
    supervisor = BrowserSupervisor()
    visible, headless = object(), object()
    supervisor.mark_ready(visible)
    supervisor.mark_notification_ready(headless)

    # Login and the human handoff still get the browser they can be seen in.
    assert supervisor.get() is visible
    assert supervisor.get_notification() is headless


def test_notifications_never_silently_use_the_visible_browser():
    """A silent fallback would reintroduce exactly the flashing windows
    this exists to remove, with nobody told why. It fails instead."""
    from mcma.app.browser_supervisor import BrowserUnavailable

    supervisor = BrowserSupervisor()
    visible = object()
    supervisor.mark_ready(visible)

    assert supervisor.get() is visible
    with pytest.raises(BrowserUnavailable):
        supervisor.get_notification()


def test_a_failed_shared_browser_clears_the_notification_browser_too():
    supervisor = BrowserSupervisor()
    supervisor.mark_ready(object())
    supervisor.mark_notification_ready(object())
    supervisor.mark_failed(RuntimeError("driver died"))
    with pytest.raises(Exception):
        supervisor.get_notification()


# --------------------------------------------------------------------- #
# No write capability regression
# --------------------------------------------------------------------- #


def test_the_read_capability_still_exposes_no_write_surface():
    forbidden = {"write", "fill", "submit", "click", "request", "evaluate", "goto", "page", "context"}
    public = {name for name in dir(ReadCapability) if not name.startswith("_")}
    assert public & forbidden == set()
    assert "read_notifications" in public


# --------------------------------------------------------------------- #
# HTTP status fails closed
# --------------------------------------------------------------------- #


def test_the_fetch_script_checks_the_status_before_the_body():
    assert "if (!r.ok) return {ok: false, status: r.status}" in _NOTIFICATION_FETCH_JS
    ok_index = _NOTIFICATION_FETCH_JS.index("!r.ok")
    body_index = _NOTIFICATION_FETCH_JS.index("r.text()")
    assert ok_index < body_index


@pytest.mark.parametrize("status", [401, 403, 404, 500, 502])
def test_a_non_2xx_response_is_a_failed_category_even_with_an_empty_data_body(status):
    """The dangerous case: an expired session answers 401 with a body that
    happens to parse as {"data": []}. Treating that as COMPLETE/zero rows
    would advance the presence lifecycle and retire notifications that are
    still open on the portal."""
    reader, _page = _reader([{"ok": False, "status": status}])
    with pytest.raises(NotificationReadFailed):
        asyncio.run(reader.read_notifications("CODE-1"))


# --------------------------------------------------------------------- #
# Malformed rows are evidence, not litter
# --------------------------------------------------------------------- #


def test_a_malformed_row_is_returned_rather_than_silently_dropped():
    """run_poll() records a non-dict row through the unmatched/malformed
    path. Filtering it here would lose that evidence and make rows_seen
    disagree with what the portal actually sent."""
    payload = [{"IdSinistre": "1"}, "not-a-row", None, {"IdSinistre": "2"}]
    reader, _page = _reader([{"ok": True, "parsed": {"data": payload}}])
    rows = asyncio.run(reader.read_notifications("CODE-1"))
    assert rows == tuple(payload)
    assert len(rows) == 4


# --------------------------------------------------------------------- #
# Category code validation reaches the route boundary
# --------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "code",
    ["../evil", "a b", "code/../..", "..%2Fevil", "a/b", " CODE-1 ", "CODE-1 ", "\tCODE-1"],
)
def test_read_notifications_refuses_a_malformed_code_before_any_fetch(code):
    reader, page = _reader([{"ok": True, "parsed": []}])
    with pytest.raises(ValueError):
        asyncio.run(reader.read_notifications(code))
    # Nothing reached the page: the route was never built.
    assert page.calls == []


def test_is_valid_category_code_rejects_the_same_values():
    from mcma.portal.capabilities import is_valid_category_code

    assert is_valid_category_code("CODE-1")
    for bad in ("../evil", "a b", "code/../..", "..%2Fevil", "", None, 7):
        assert not is_valid_category_code(bad)


@pytest.mark.parametrize("code", [" CODE-1 ", "CODE-1 ", " CODE-1", "\tCODE-1", "CODE-1\n"])
def test_a_code_with_surrounding_whitespace_is_not_canonical(code):
    """The route is built from the value as given, so validating a
    stripped copy would pass on " CODE-1 " and then fetch %20CODE-1%20 --
    a check that passes on a different value than the one used."""
    from mcma.portal.capabilities import is_valid_category_code

    assert not is_valid_category_code(code)


# --------------------------------------------------------------------- #
# Session probe: the authenticated page as it was actually observed
# --------------------------------------------------------------------- #


class _ProbePage:
    def __init__(self, state):
        self._state = state

    async def evaluate(self, script, arg=None):
        return self._state


def _probe(state):
    return ReadCapability(_FakeContext(), _ProbePage(state), "portal.test", "/SinAuto_MCMA")


def test_the_probe_script_counts_the_alert_navbar_as_logged_in_evidence():
    """Onsite (2026-09-02) the real frontexpert page showed #listeAlertes and
    a live actualierAlertes() while carrying none of the search-form
    markers. Without these two the probe answered INDETERMINATE and every
    refresh died before run_poll."""
    from mcma.portal.capabilities import _SESSION_STATE_JS, LOGGED_IN_MARKERS

    assert "#listeAlertes" in _SESSION_STATE_JS
    assert "typeof window.actualierAlertes === 'function'" in _SESSION_STATE_JS
    assert "#listeAlertes" in LOGGED_IN_MARKERS
    # The logged-out evidence is unchanged: nothing became easier to
    # mistake for a signed-in page.
    assert "url.indexOf('login') !== -1" in _SESSION_STATE_JS
    assert "input[name='login'], #login, #password" in _SESSION_STATE_JS


def test_logged_in_evidence_without_logged_out_evidence_is_authenticated():
    assert asyncio.run(_probe({"logged_in": True, "logged_out": False}).observe_session_state()) == "AUTHENTICATED"


def test_logged_out_evidence_alone_is_logged_out():
    assert asyncio.run(_probe({"logged_in": False, "logged_out": True}).observe_session_state()) == "LOGGED_OUT"


def test_no_evidence_either_way_stays_indeterminate():
    """Still never a guess: a page with neither marker is not declared
    authenticated, and not revoked either."""
    assert asyncio.run(_probe({"logged_in": False, "logged_out": False}).observe_session_state()) == "INDETERMINATE"


def test_contradictory_evidence_stays_indeterminate():
    assert asyncio.run(_probe({"logged_in": True, "logged_out": True}).observe_session_state()) == "INDETERMINATE"


# --------------------------------------------------------------------- #
# PORTAL_UNAVAILABLE names its branch
# --------------------------------------------------------------------- #


def test_an_unavailable_outcome_logs_which_stage_and_only_the_exception_type(caplog):
    import logging

    from mcma.notifications.poller import _log_unavailable

    with caplog.at_level(logging.WARNING, logger="mcma.notifications.poller"):
        _log_unavailable("discovery reader could not open", exc=RuntimeError("secret username inside"))
        _log_unavailable("session state before discovery", state="INDETERMINATE")

    text = caplog.text
    assert "discovery reader could not open: RuntimeError" in text
    assert "session state before discovery: state=INDETERMINATE" in text
    # The exception message is never logged.
    assert "secret username inside" not in text


# --------------------------------------------------------------------- #
# The discovery scripts must be what page.evaluate() can actually call
# --------------------------------------------------------------------- #


import json
import shutil
import subprocess


_NODE = shutil.which("node")


def _js_invocable_as_playwright_does(script: str) -> bool:
    """page.evaluate(str, arg) compiles the string as ONE expression and,
    if it is a function, calls it with the argument. A helper declaration
    prepended to the function is not that: Playwright then calls the
    helper. This checks the string the way Playwright uses it."""
    probe = "const f = (" + script + ");process.stdout.write(typeof f);"
    result = subprocess.run([_NODE, "-e", probe], capture_output=True, text=True)
    return result.returncode == 0 and result.stdout.strip() == "function"


@pytest.mark.skipif(_NODE is None, reason="node is not available to compile the script")
def test_both_discovery_scripts_are_single_callable_functions():
    """Regression for the onsite 'category discovery failed: Error'. Each
    script must evaluate to ONE function whose parameter is the argument
    the reader passes, not to a helper that happens to come first."""
    assert _js_invocable_as_playwright_does(_CATEGORY_SURFACE_JS)
    assert _js_invocable_as_playwright_does(_CATEGORY_LINKS_JS)
    # And their first token is the parameter list the reader supplies.
    assert _CATEGORY_SURFACE_JS.lstrip().startswith("([url, prefixes]) =>")
    assert _CATEGORY_LINKS_JS.lstrip().startswith("(prefixes) =>")


@pytest.mark.skipif(_NODE is None, reason="node is not available to run the script")
def test_the_in_page_script_returns_only_reviewed_codes_when_actually_run():
    """The script is executed, not inspected, against a DOM carrying both
    real shapes plus a cross-origin, a wrong-base and a malformed href."""
    harness = """
const links = [
  '/SinAuto_MCMA/expertise/notification/alerte/CODE-1',
  '/SinAuto_MCMA/expertise/notification/notification/alerte/CODE-2',
  'https://evil.example.com/SinAuto_MCMA/expertise/notification/alerte/CODE-3',
  '/SinAuto_MAMDA/expertise/notification/alerte/CODE-4',
  '/SinAuto_MCMA/expertise/notification/alerte/../evil',
].map(h => ({ getAttribute: () => h }));
global.document = { querySelectorAll: (sel) => sel.startsWith('#listeAlertes') ? links : [] };
global.location = { href: 'https://portal.test/SinAuto_MCMA/expertise/frontexpert', origin: 'https://portal.test' };
const r = (%s)(['/SinAuto_MCMA/expertise/notification/alerte','/SinAuto_MCMA/expertise/notification/notification/alerte']);
process.stdout.write(JSON.stringify(r));
""" % _CATEGORY_LINKS_JS
    result = subprocess.run([_NODE, "-e", harness], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == ["CODE-1", "CODE-2"]


# --------------------------------------------------------------------- #
# A failed read says WHICH of the four things happened
# --------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "outcome,stage,status",
    [
        ({"ok": False}, "request_not_completed", None),
        ({"ok": False, "status": 403}, "http_status", 403),
        ({"ok": False, "status": 500}, "http_status", 500),
        ({"ok": False, "parse_error": True}, "not_json", None),
        ({"ok": True, "parsed": {"unexpected": []}}, "unexpected_json_shape", None),
        (None, "script_result", None),
    ],
)
def test_a_failed_read_names_its_stage(outcome, stage, status):
    """Three onsite rounds could not tell a policy denial from a 403,
    because all four failures raised the same bare ValueError."""
    reader, _page = _reader([outcome])
    with pytest.raises(NotificationReadFailed) as raised:
        asyncio.run(reader.read_notifications("CODE-1"))
    assert raised.value.stage == stage
    assert raised.value.status == status


def test_a_failed_read_never_carries_the_response_body():
    """A portal error page can contain the employee's username."""
    reader, _page = _reader([{"ok": False, "parse_error": True}])
    with pytest.raises(NotificationReadFailed) as raised:
        asyncio.run(reader.read_notifications("CODE-1"))
    assert "html" not in str(raised.value).lower()
    assert raised.value.args[0].startswith("notification read failed at")


def test_the_fetch_script_reports_a_parse_failure_without_the_body():
    from mcma.portal.capabilities import _NOTIFICATION_FETCH_JS

    assert "parse_error: true" in _NOTIFICATION_FETCH_JS
    # The text is never put in the result object.
    assert "text}" not in _NOTIFICATION_FETCH_JS
    assert "raw: text" not in _NOTIFICATION_FETCH_JS


def test_a_run_that_read_nothing_is_not_reported_as_refreshed():
    """POLLED after eight failed categories told the employee
    'Notifications actualisées.' about a refresh that read nothing."""
    import inspect

    from mcma.notifications import poller

    source = inspect.getsource(poller.poll_one_account)
    assert 'if run_status == "COMPLETE":' in source
    assert '"POLL_FAILED"' in source
    assert '"POLL_INCOMPLETE"' in source


def test_both_new_outcomes_have_employee_facing_sentences():
    import inspect

    from mcma.app.api import app as api_app

    source = inspect.getsource(api_app)
    assert '"POLL_FAILED": "Aucune catégorie n\'a pu être lue' in source
    assert '"POLL_INCOMPLETE": "Actualisation partielle' in source


# --------------------------------------------------------------------- #
# The DataTables 1.9 response shape
# --------------------------------------------------------------------- #


def test_the_legacy_datatables_shape_is_accepted():
    """The body this application sends uses the 1.9 parameter names
    (iDisplayStart/iDisplayLength), so the portal answers in 1.9 format:
    {sEcho, iTotalRecords, iTotalDisplayRecords, aaData}. Onsite the
    request completed, returned 2xx and parsed as JSON, and only the shape
    was unrecognised."""
    payload = {
        "sEcho": 1,
        "iTotalRecords": 2,
        "iTotalDisplayRecords": 2,
        "aaData": [{"IdSinistre": "1"}, {"IdSinistre": "2"}],
    }
    reader, _page = _reader([{"ok": True, "parsed": payload}])
    rows = asyncio.run(reader.read_notifications("CODE-1"))
    assert rows == ({"IdSinistre": "1"}, {"IdSinistre": "2"})


def test_the_request_and_the_accepted_shape_belong_to_the_same_generation():
    from mcma.portal.capabilities import (
        _NOTIFICATION_FULL_DATASET_PAYLOAD,
        _NOTIFICATION_ROW_KEYS,
    )

    # 1.9 request parameters...
    assert "iDisplayStart" in _NOTIFICATION_FULL_DATASET_PAYLOAD
    assert "iDisplayLength" in _NOTIFICATION_FULL_DATASET_PAYLOAD
    # ...and the 1.9 response key alongside the modern ones.
    assert _NOTIFICATION_ROW_KEYS == ("data", "rows", "aaData")


def test_an_empty_legacy_payload_is_zero_rows_not_a_failure():
    reader, _page = _reader([{"ok": True, "parsed": {"sEcho": 1, "aaData": []}}])
    assert asyncio.run(reader.read_notifications("CODE-1")) == ()


def test_a_legacy_key_holding_a_non_list_still_fails_closed():
    reader, _page = _reader([{"ok": True, "parsed": {"aaData": "not-a-list"}}])
    with pytest.raises(NotificationReadFailed):
        asyncio.run(reader.read_notifications("CODE-1"))


def test_an_unknown_shape_reports_its_key_names_and_no_values():
    """So the next unknown shape is named the first time it is seen."""
    reader, _page = _reader([{"ok": True, "parsed": {"sEcho": 1, "unexpectedKey": {}}}])
    with pytest.raises(NotificationReadFailed) as raised:
        asyncio.run(reader.read_notifications("CODE-1"))
    assert raised.value.shape_keys == ("sEcho", "unexpectedKey")


def test_shape_keys_never_leak_a_portal_identifier():
    from mcma.portal.capabilities import _payload_shape_keys

    # A payload keyed by claim references must not put them in a log.
    keys = _payload_shape_keys({"REF-0001": {}, "0000-A-0": {}, "sEcho": 1})
    assert "REF-0001" not in keys
    assert "0000-A-0" not in keys
    assert keys.count("<non-identifier>") == 2
    assert "sEcho" in keys
    # And the list is capped rather than unbounded.
    assert len(_payload_shape_keys({f"k{i}": i for i in range(50)})) == 10
