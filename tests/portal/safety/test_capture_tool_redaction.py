"""The capture tool's output must be safe to email.

It runs on a real portal, with a real dossier open, while a human types a
real password and OTP. The property under test is that none of that can
reach the file -- proven with markers obvious enough that a failure
message says exactly what leaked.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools"))

from capture_sinauto_write_evidence import (  # noqa: E402
    BLOCKED,
    MCMA_BASE,
    PORTAL_HOST,
    Capture,
    field_names,
    is_blocked,
    is_in_scope,
    normalize_path,
)

SECRETS = (
    "SECRET_PASSWORD",
    "OTP_123456",
    "REGISTRATION_77001_C_3",
    "CLAIM_699001",
    "CLIENT_JOHN_DOE",
    "12345.67",
)


def _document_text(capture, selectors=None, functions=None):
    return json.dumps(capture.to_document(selectors or {}, functions or {}))


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
    assert ".py" not in source.split("OUTPUT_DIR =")[1].split("\n")[0]
    assert "write-contract-capture-" in source        # JSON only


def test_dom_probes_report_presence_only_from_a_fixed_list():
    from capture_sinauto_write_evidence import PROBE_FUNCTIONS, PROBE_SELECTORS

    source = (Path(__file__).resolve().parents[3] / "tools"
              / "capture_sinauto_write_evidence.py").read_text(encoding="utf-8")
    # Booleans, never contents.
    assert "document.querySelector(s) !== null" in source
    assert ".value" not in source
    assert ".textContent" not in source
    assert ".innerHTML" not in source
    # Fixed lists; globals are never enumerated.
    assert all(s.startswith("#") for s in PROBE_SELECTORS)
    assert "Object.keys(window)" not in source
    assert len(PROBE_FUNCTIONS) == 3
