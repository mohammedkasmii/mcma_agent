"""
INC-07 -- permanent final-endpoint blocking (INV-4, ADR-0004). Checked
against the canonical path, so it cannot be bypassed by trailing slashes,
encoding, or duplicate separators.
"""

import mock_server
from mcma.portal.canonical import canonicalize_request
from mcma.portal.contracts import Decision, evaluate_request
from mcma.portal.final_endpoints import PERMANENTLY_BLOCKED_ENDPOINTS, is_permanently_blocked

ALLOWED_HOST = "127.0.0.1:8080"


def _canonical_path(route):
    result = canonicalize_request(
        raw_url=f"http://{ALLOWED_HOST}{route}", raw_method="POST",
        raw_content_type="application/x-www-form-urlencoded", raw_body="",
    )
    assert result is not None
    return result


def test_every_documented_final_endpoint_is_permanently_blocked():
    for name, route in mock_server.FINAL_ENDPOINT_ROUTES.items():
        canonical = _canonical_path(route)
        assert is_permanently_blocked(canonical.path), name
        assert evaluate_request(canonical, (), ALLOWED_HOST) is Decision.DENY, name


def test_final_endpoint_names_match_the_documented_set():
    assert set(PERMANENTLY_BLOCKED_ENDPOINTS) == set(mock_server.FINAL_ENDPOINT_ROUTES)


def test_create_devis_det_is_absent_from_the_permanent_block_list():
    """createDevisDet is a phantom (no real portal counterpart), not a final
    dossier action -- it must never be added to this list."""
    assert not any("createDevisDet" in name for name in PERMANENTLY_BLOCKED_ENDPOINTS)


def test_create_devis_det_is_denied_via_default_deny_not_the_final_list():
    canonical = _canonical_path("/SinAuto_MCMA/expertise/gestionExpert/createDevisDet")
    assert not is_permanently_blocked(canonical.path)
    assert evaluate_request(canonical, (), ALLOWED_HOST) is Decision.DENY


def test_final_endpoint_check_runs_against_the_canonical_path_not_the_raw_one():
    raw_result = canonicalize_request(
        raw_url=f"http://{ALLOWED_HOST}/SinAuto_MCMA/expertise/gestiongarage/garageModifierValDevis/",
        raw_method="POST", raw_content_type="application/x-www-form-urlencoded", raw_body="",
    )
    assert raw_result is not None
    assert raw_result.path == "/SinAuto_MCMA/expertise/gestiongarage/garageModifierValDevis"
    assert is_permanently_blocked(raw_result.path)
