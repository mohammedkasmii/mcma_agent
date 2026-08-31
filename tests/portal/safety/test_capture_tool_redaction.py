"""The capture tool's output must be safe to email.

It runs on a real portal, with a real dossier open, while a human types a
real password and OTP. The property under test is that none of that can
reach the file -- proven with markers obvious enough that a failure
message says exactly what leaked.
"""

import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools"))

from capture_sinauto_write_evidence import (  # noqa: E402
    BLOCKED,
    MCMA_BASE,
    PORTAL_HOST,
    PROBE_FUNCTIONS,
    WORKFLOWS,
    Capture,
    field_names,
    is_blocked,
    is_in_scope,
    normalize_path,
    probe_dom,
    safe_field_names,
)

SECRETS = (
    "SECRET_PASSWORD",
    "OTP_123456",
    "REGISTRATION_77001_C_3",
    "CLAIM_699001",
    "CLIENT_JOHN_DOE",
    "12345.67",
)


def _document_text(capture, selectors=None, functions=None, workflow="mode-normal"):
    return json.dumps(capture.to_document(workflow, selectors or {}, functions or {}))


# --------------------------------------------------------------------- #
# Names yes, values never
# --------------------------------------------------------------------- #


def test_a_form_body_yields_field_names_and_no_values():
    body = (
        "IdRubrique=1&MontantHT=12345.67&Taxe=2000.00"
        "&Matricule=REGISTRATION_77001_C_3&NomSocietaire=CLIENT_JOHN_DOE"
    )
    names = field_names("application/x-www-form-urlencoded", body)
    assert names == ["IdRubrique", "Matricule", "MontantHT", "NomSocietaire", "Taxe"]
    for secret in SECRETS:
        assert secret not in json.dumps(names)


def test_a_json_body_yields_keys_and_no_values():
    body = json.dumps({"idSinistre": "CLAIM_699001", "montant": "12345.67"})
    assert field_names("application/json", body) == ["idSinistre", "montant"]


def test_an_unparseable_body_yields_no_names_rather_than_raw_text():
    """Falling back to the raw body would be exactly the leak this
    prevents."""
    names = field_names("application/octet-stream", "SECRET_PASSWORD\x00OTP_123456")
    assert names == ["<unparseable>"]
    for secret in SECRETS:
        assert secret not in json.dumps(names)


def test_a_recorded_request_never_carries_credentials(tmp_path):
    capture = Capture()
    capture.record_request(
        "POST",
        f"https://{PORTAL_HOST}{MCMA_BASE}/front/Login/login?redirect=CLAIM_699001",
        "application/x-www-form-urlencoded",
        "login=CLIENT_JOHN_DOE&password=SECRET_PASSWORD&otp=OTP_123456",
    )
    text = _document_text(capture)
    for secret in SECRETS:
        assert secret not in text, f"{secret} leaked into the capture"
    # The shape survives.
    event = capture.events[0]
    assert event["body_field_names"] == ["login", "otp", "password"]
    assert event["query_field_names"] == ["redirect"]


def test_a_full_capture_document_contains_no_secret(tmp_path):
    capture = Capture()
    capture.record_request(
        "POST",
        f"https://{PORTAL_HOST}{MCMA_BASE}/expertise/gestionExpert/createRapportDefDet",
        "application/x-www-form-urlencoded",
        "IdRubrique=1&MontantHT=12345.67&Matricule=REGISTRATION_77001_C_3",
    )
    capture.record_response(
        f"https://{PORTAL_HOST}{MCMA_BASE}/expertise/gestionExpert/createRapportDefDet",
        200, "application/json",
    )
    capture.record_blocked("POST", f"https://{PORTAL_HOST}{MCMA_BASE}/expertise/enregistrerMission")

    out = tmp_path / "capture.json"
    out.write_text(_document_text(capture), encoding="utf-8")
    written = out.read_text(encoding="utf-8")
    for secret in SECRETS:
        assert secret not in written


def test_no_cookie_or_authorization_header_is_ever_recorded():
    """The recorder has no parameter for them -- headers are not passed in
    at all, so there is nothing to forget to strip."""
    import inspect

    signature = inspect.signature(Capture.record_request)
    assert set(signature.parameters) == {"self", "method", "url", "content_type", "body"}
    # And the recorded events carry no header data of any kind.
    capture = Capture()
    capture.record_request("POST", f"https://{PORTAL_HOST}{MCMA_BASE}/x", None, None)
    assert set(capture.events[0]) == {
        "seq", "kind", "method", "path_template", "content_type",
        "query_field_names", "body_field_names",
    }


# --------------------------------------------------------------------- #
# Identifiers are normalized
# --------------------------------------------------------------------- #


@pytest.mark.parametrize("path,expected", [
    (
        f"{MCMA_BASE}/expertise/gestionExpert/getSinistre/idSinistre/699001/rubrique/gestionexpert-index",
        f"{MCMA_BASE}/expertise/gestionExpert/getSinistre/idSinistre/{{id}}/rubrique/gestionexpert-index",
    ),
    (f"{MCMA_BASE}/expertise/mission/612001", f"{MCMA_BASE}/expertise/mission/{{id}}"),
    (f"{MCMA_BASE}/expertise/gestionExpert/createRapportDefDet",
     f"{MCMA_BASE}/expertise/gestionExpert/createRapportDefDet"),
])
def test_path_identifiers_are_replaced_with_placeholders(path, expected):
    assert normalize_path(path) == expected


def test_a_claim_identifier_cannot_reach_the_document():
    capture = Capture()
    capture.record_request(
        "GET", f"https://{PORTAL_HOST}{MCMA_BASE}/expertise/gestionExpert/getSinistre/idSinistre/699001",
        None, None,
    )
    text = _document_text(capture)
    assert "699001" not in text
    assert "{id}" in text


# --------------------------------------------------------------------- #
# Scope
# --------------------------------------------------------------------- #


def test_only_mcma_traffic_on_the_reviewed_host_is_in_scope():
    assert is_in_scope(f"https://{PORTAL_HOST}{MCMA_BASE}/expertise/frontexpert")
    # MAMDA is excluded: MAMDA writes are prohibited, so its traffic can
    # never be write-contract evidence.
    assert not is_in_scope(f"https://{PORTAL_HOST}/SinAuto_MAMDA/expertise/frontexpert")
    # Everything else.
    assert not is_in_scope("https://evil.example.com/SinAuto_MCMA/expertise/x")
    assert not is_in_scope("https://cdn.example.com/analytics.js")
    assert not is_in_scope(f"https://{PORTAL_HOST}.evil.com{MCMA_BASE}/x")


# --------------------------------------------------------------------- #
# Final actions cannot be sent, even by a human misclick
# --------------------------------------------------------------------- #


@pytest.mark.parametrize("name", BLOCKED)
def test_every_final_action_is_blocked_during_capture(name):
    assert is_blocked(f"{MCMA_BASE}/expertise/{name}")


def test_the_blocked_list_matches_the_permanent_one():
    from mcma.portal.final_endpoints import PERMANENTLY_BLOCKED_ENDPOINTS

    assert set(BLOCKED) == set(PERMANENTLY_BLOCKED_ENDPOINTS)


def test_a_blocked_attempt_is_recorded_without_the_identifier():
    capture = Capture()
    capture.record_blocked(
        "POST", f"https://{PORTAL_HOST}{MCMA_BASE}/expertise/cloturerMission/idSinistre/699001")
    text = _document_text(capture)
    assert "cloturerMission" in text
    assert "699001" not in text


def test_the_tool_never_fabricates_a_success_response():
    """A fake 200 would tell the portal's own JavaScript that a final
    action succeeded. Blocked requests are aborted."""
    source = (Path(__file__).resolve().parents[3] / "tools"
              / "capture_sinauto_write_evidence.py").read_text(encoding="utf-8")
    assert 'route.abort("blockedbyclient")' in source
    assert "route.fulfill" not in source


# --------------------------------------------------------------------- #
# It is an observer, not an agent
# --------------------------------------------------------------------- #


def test_the_tool_performs_no_portal_actions_itself():
    source = (Path(__file__).resolve().parents[3] / "tools"
              / "capture_sinauto_write_evidence.py").read_text(encoding="utf-8")
    for action in (".click(", ".fill(", ".select_option(", ".check(", ".type(", ".press("):
        assert action not in source, f"the observer must not {action}"


def test_the_tool_never_writes_python_or_contracts():
    """Portal data must not be able to authorize a route. The capture is
    reviewed by a human before anything becomes a contract."""
    source = (Path(__file__).resolve().parents[3] / "tools"
              / "capture_sinauto_write_evidence.py").read_text(encoding="utf-8")
    assert "RouteContract(" not in source
    # Output is JSON under var/evidence, never Python.
    assert 'OUTPUT_DIR = REPO_ROOT / "var" / "evidence"' in source
    assert 'write-contract-{workflow}-{stamp}.json' in source
    assert ".write_text" in source and "mcma/" not in source.split("OUTPUT_DIR")[1]


def test_dom_probes_report_presence_only_from_a_fixed_list():
    source = (Path(__file__).resolve().parents[3] / "tools"
              / "capture_sinauto_write_evidence.py").read_text(encoding="utf-8")
    # Assert on the JS that actually runs in the page, not on the whole
    # Python file -- selectors.values() is not a DOM read.
    scripts = [line for line in source.splitlines() if "=> Object.fromEntries" in line]
    assert len(scripts) == 2
    joined = "\n".join(scripts)
    assert "document.querySelector(s) !== null" in joined
    assert "typeof window[n] === 'function'" in joined
    for forbidden in (".value", ".textContent", ".innerHTML", "outerHTML"):
        assert forbidden not in joined
    # Fixed lists; globals are never enumerated.
    for selectors in WORKFLOWS.values():
        assert all(s.startswith("#") for s in selectors)
    assert "Object.keys(window)" not in source
    assert len(PROBE_FUNCTIONS) == 3



# --------------------------------------------------------------------- #
# C.2.1 -- the DOM probe must run while the page is OPEN
# --------------------------------------------------------------------- #


class _OpenPage:
    """Answers evaluate() only while it is open, exactly as a real page
    does -- so a probe that waits for the close event fails here."""

    def __init__(self, present=()):
        self.closed = False
        self._present = set(present)
        self.evaluate_calls = 0

    async def evaluate(self, script, arg=None):
        self.evaluate_calls += 1
        if self.closed:
            raise RuntimeError("Target page, context or browser has been closed")
        if "querySelector" in script:
            return {s: s in self._present for s in arg}
        return {n: n in self._present for n in arg}


def test_the_dom_probe_runs_against_an_open_page():
    """The bug this fixes: probing after the close event collected network
    shapes and silently lost every piece of DOM evidence -- which is most
    of what the audit says is missing."""
    page = _OpenPage(present={"#MontantHT", "DevisCalculerMontantCharge"})
    selectors, functions = asyncio.run(probe_dom(page, "mode-normal"))

    assert page.closed is False
    assert page.evaluate_calls == 2
    assert selectors["#MontantHT"] is True
    assert selectors["#VehRepareI"] is False
    assert functions["DevisCalculerMontantCharge"] is True


def test_probing_a_closed_page_fails_loudly_rather_than_returning_nothing():
    page = _OpenPage()
    page.closed = True
    with pytest.raises(RuntimeError):
        asyncio.run(probe_dom(page, "mode-normal"))


def test_probe_results_are_booleans_only():
    page = _OpenPage(present={"#MontantHT"})
    selectors, functions = asyncio.run(probe_dom(page, "garage-conventionne"))
    assert all(isinstance(v, bool) for v in selectors.values())
    assert all(isinstance(v, bool) for v in functions.values())


# --------------------------------------------------------------------- #
# Workflow is explicit and labelled
# --------------------------------------------------------------------- #


def test_only_the_two_approved_workflows_exist():
    assert sorted(WORKFLOWS) == ["garage-conventionne", "mode-normal"]


def test_each_workflow_probes_its_own_selectors():
    """A union across two dossiers would answer the wrong question."""
    normal = set(WORKFLOWS["mode-normal"])
    pec = set(WORKFLOWS["garage-conventionne"])
    assert "#VehRepareI" in normal and "#VehRepareI" not in pec
    assert "#MontantHTValide" in pec and "#MontantHTValide" not in normal
    # Shared header fields appear in both.
    assert "#Kilometrage" in normal and "#Kilometrage" in pec


def test_the_output_document_is_labelled_with_its_workflow():
    for workflow in WORKFLOWS:
        document = Capture().to_document(workflow, {}, {})
        assert document["workflow"] == workflow


def test_an_unknown_workflow_is_refused():
    with pytest.raises(KeyError):
        asyncio.run(probe_dom(_OpenPage(), "something-else"))


def test_probe_selectors_and_functions_are_fixed_lists():
    for selectors in WORKFLOWS.values():
        assert all(s.startswith("#") for s in selectors)
    assert PROBE_FUNCTIONS == (
        "CalculerMntArrete", "CalculerMontantDommage", "DevisCalculerMontantCharge",
    )


# --------------------------------------------------------------------- #
# The blocklist is production's, and path handling is hardened
# --------------------------------------------------------------------- #


def test_the_blocklist_is_the_production_object_not_a_copy():
    from mcma.portal.final_endpoints import PERMANENTLY_BLOCKED_ENDPOINTS

    assert BLOCKED is PERMANENTLY_BLOCKED_ENDPOINTS


@pytest.mark.parametrize("path", [
    f"{MCMA_BASE}/expertise/%2e%2e/enregistrerMission",
    f"{MCMA_BASE}//expertise/cloturerMission",
    f"{MCMA_BASE}/expertise/../expertise/validerDevis",
    f"{MCMA_BASE}/expertise/./ajouterDocument",
])
def test_encoded_and_traversal_paths_cannot_bypass_blocking(path):
    """A path that cannot be canonicalized is treated as blocked. Refusing
    an ambiguous request costs a retry; allowing one could close a claim."""
    assert is_blocked(path) is True


def test_ordinary_portal_traffic_is_not_blocked():
    """Hardening the path check must not default-deny the whole portal."""
    for path in (
        f"{MCMA_BASE}/expertise/frontexpert",
        f"{MCMA_BASE}/expertise/gestionExpert/createRapportDefDet",
        f"{MCMA_BASE}/expertise/gestiongarage/updateDevisDet",
        f"{MCMA_BASE}/css/portal.css",
    ):
        assert is_blocked(path) is False


# --------------------------------------------------------------------- #
# Query keys get the same treatment as body keys
# --------------------------------------------------------------------- #


def test_query_values_never_persist_and_malformed_keys_are_dropped():
    capture = Capture()
    capture.record_request(
        "GET",
        f"https://{PORTAL_HOST}{MCMA_BASE}/expertise/x"
        "?ref=CLAIM_699001&CLIENT_JOHN_DOE+bad+key=1&ok=2",
        None, None,
    )
    text = _document_text(capture)
    for secret in SECRETS:
        assert secret not in text
    assert capture.events[0]["query_field_names"] == ["ok", "ref"]


def test_safe_field_names_drops_anything_that_is_not_a_name():
    assert safe_field_names(["good_name", "also.good[0]", "bad key", "x" * 200, ""]) == [
        "also.good[0]", "good_name",
    ]


@pytest.mark.parametrize("raw", [
    "SECRET_PASSWORD",
    "OTP_123456",
    "REGISTRATION_77001_C_3",
    "CLIENT_JOHN_DOE",
    "SECRET_PASSWORD&OTP_123456",
    "login CLIENT_JOHN_DOE password SECRET_PASSWORD",
])
def test_a_malformed_bare_body_can_never_become_a_field_name(raw):
    """parse_qsl turns a bare fragment into one enormous "key", and keys
    ARE persisted. A form field must have arrived as a real name=value
    pair."""
    names = field_names("application/x-www-form-urlencoded", raw)
    assert names == ["<unparseable>"]
    for secret in SECRETS:
        assert secret not in json.dumps(names)
