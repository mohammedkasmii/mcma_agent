"""
INC-07 -- RouteContract validation, workflow separation, and the pure
evaluate_request decision (no Playwright object involved).
"""

import pytest

from mcma.portal.canonical import canonicalize_request
from mcma.portal.contracts import Decision, RouteContract, contracts_for_workflow, evaluate_request

ALLOWED_HOST = "127.0.0.1:8080"

NORMAL_ADD_ROW = RouteContract(
    host=ALLOWED_HOST,
    route="/SinAuto_MCMA/expertise/gestionExpert/createRapportDefDet",
    method="POST",
    query_fields=frozenset(),
    content_type="application/x-www-form-urlencoded",
    body_fields=frozenset(
        {"IdRubrique", "MontantHT", "Taxe", "MontantTTC", "TauxVetuste", "MontantVetuste", "TempRowId"}
    ),
    capability="row_write",
    operation_type="add_row",
    workflow="MODE_NORMAL",
)

PEC_EDIT_ROW = RouteContract(
    host=ALLOWED_HOST,
    route="/SinAuto_MCMA/expertise/gestionexpert/updateDevisDet",
    method="POST",
    query_fields=frozenset(),
    content_type="application/x-www-form-urlencoded",
    body_fields=frozenset(
        {"IdDevisDet", "MontantHTValide", "TaxeValide", "MontantTTCValide", "TauxVetusteValide", "MontantVetusteValide", "SubmissionNonce"}
    ),
    capability="row_write",
    operation_type="edit_row",
    workflow="GARAGE_CONVENTIONNE",
)

SHARED_READ = RouteContract(
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

ALL_CONTRACTS = (NORMAL_ADD_ROW, PEC_EDIT_ROW, SHARED_READ)


def _canonical(url, method="GET", content_type=None, body=None):
    result = canonicalize_request(raw_url=url, raw_method=method, raw_content_type=content_type, raw_body=body)
    assert result is not None
    return result


# --------------------------------------------------------------------- #
# RouteContract construction is fail-closed: a malformed contract raises
# and therefore can never enter a policy list.
# --------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(route="relative/path"),
        dict(route="/x/"),
        dict(route="/x/../y"),
        dict(route="/x//y"),
        dict(method="post"),
        dict(method=""),
        dict(content_type="multipart/form-data"),
        dict(method="GET", content_type="application/json", body_fields=frozenset({"a"})),
        dict(capability=""),
        dict(operation_type=""),
        dict(host=""),
        dict(host="Example.com"),
        dict(content_type=None, body_fields=frozenset({"a"})),
    ],
)
def test_malformed_contract_is_rejected_at_construction(kwargs):
    base = dict(
        host=ALLOWED_HOST,
        route="/SinAuto_MCMA/expertise/gestionExpert/listeRapportDefDet",
        method="POST",
        query_fields=frozenset(),
        content_type="application/x-www-form-urlencoded",
        body_fields=frozenset(),
        capability="read",
        operation_type="list_rows",
    )
    base.update(kwargs)
    with pytest.raises(ValueError):
        RouteContract(**base)


# --------------------------------------------------------------------- #
# Workflow separation
# --------------------------------------------------------------------- #


def test_contracts_for_workflow_excludes_the_other_workflow():
    normal_policy = contracts_for_workflow("MODE_NORMAL", ALL_CONTRACTS)
    pec_policy = contracts_for_workflow("GARAGE_CONVENTIONNE", ALL_CONTRACTS)
    assert PEC_EDIT_ROW not in normal_policy
    assert NORMAL_ADD_ROW not in pec_policy
    assert NORMAL_ADD_ROW in normal_policy
    assert PEC_EDIT_ROW in pec_policy
    assert SHARED_READ in normal_policy and SHARED_READ in pec_policy


def test_mode_normal_contracts_cannot_authorize_pec_operation():
    normal_policy = contracts_for_workflow("MODE_NORMAL", ALL_CONTRACTS)
    canonical = _canonical(
        f"http://{ALLOWED_HOST}/SinAuto_MCMA/expertise/gestionexpert/updateDevisDet",
        method="POST",
        content_type="application/x-www-form-urlencoded",
        body="IdDevisDet=1&MontantHTValide=1&TaxeValide=1&MontantTTCValide=1&TauxVetusteValide=0&MontantVetusteValide=0&SubmissionNonce=n",
    )
    assert evaluate_request(canonical, normal_policy, ALLOWED_HOST) is Decision.DENY


def test_pec_contracts_cannot_authorize_mode_normal_operation():
    pec_policy = contracts_for_workflow("GARAGE_CONVENTIONNE", ALL_CONTRACTS)
    canonical = _canonical(
        f"http://{ALLOWED_HOST}/SinAuto_MCMA/expertise/gestionExpert/createRapportDefDet",
        method="POST",
        content_type="application/x-www-form-urlencoded",
        body="IdRubrique=7&MontantHT=1&Taxe=1&MontantTTC=1&TauxVetuste=0&MontantVetuste=0&TempRowId=t",
    )
    assert evaluate_request(canonical, pec_policy, ALLOWED_HOST) is Decision.DENY


# --------------------------------------------------------------------- #
# Pure decision: unknown route / method / payload / host; unreviewed GET
# --------------------------------------------------------------------- #


def test_allowed_loopback_read_contract_succeeds():
    canonical = _canonical(
        f"http://{ALLOWED_HOST}/SinAuto_MCMA/expertise/gestionExpert/listeRapportDefDet",
        method="POST",
        content_type="application/x-www-form-urlencoded",
        body="",
    )
    assert evaluate_request(canonical, ALL_CONTRACTS, ALLOWED_HOST) is Decision.ALLOW


def test_unknown_route_is_denied():
    canonical = _canonical(f"http://{ALLOWED_HOST}/SinAuto_MCMA/some/unknown/route")
    assert evaluate_request(canonical, ALL_CONTRACTS, ALLOWED_HOST) is Decision.DENY


def test_wrong_method_is_denied():
    canonical = _canonical(
        f"http://{ALLOWED_HOST}/SinAuto_MCMA/expertise/gestionExpert/listeRapportDefDet",
        method="GET",
    )
    assert evaluate_request(canonical, ALL_CONTRACTS, ALLOWED_HOST) is Decision.DENY


def test_wrong_payload_shape_is_denied():
    canonical = _canonical(
        f"http://{ALLOWED_HOST}/SinAuto_MCMA/expertise/gestionExpert/createRapportDefDet",
        method="POST",
        content_type="application/x-www-form-urlencoded",
        body="IdRubrique=7&MontantHT=1&Taxe=1&MontantTTC=1&TauxVetuste=0&MontantVetuste=0&TempRowId=t&MontantChargeMutuelle=999",
    )
    assert evaluate_request(canonical, ALL_CONTRACTS, ALLOWED_HOST) is Decision.DENY


def test_unreviewed_get_is_denied():
    canonical = _canonical(f"http://{ALLOWED_HOST}/SinAuto_MCMA/expertise/gestionexpert/index")
    assert evaluate_request(canonical, ALL_CONTRACTS, ALLOWED_HOST) is Decision.DENY


def test_third_party_host_is_denied():
    canonical = _canonical("http://evil.example.com/SinAuto_MCMA/expertise/gestionExpert/listeRapportDefDet", method="GET")
    assert evaluate_request(canonical, ALL_CONTRACTS, ALLOWED_HOST) is Decision.DENY


def test_ambiguous_canonicalization_failure_is_denied():
    assert evaluate_request(None, ALL_CONTRACTS, ALLOWED_HOST) is Decision.DENY


def test_final_endpoint_denied_even_if_a_contract_wrongly_claims_it():
    rogue_contract = RouteContract(
        host=ALLOWED_HOST,
        route="/SinAuto_MCMA/expertise/gestiongarage/garageModifierValDevis",
        method="POST",
        query_fields=frozenset(),
        content_type="application/x-www-form-urlencoded",
        body_fields=frozenset(),
        capability="row_write",
        operation_type="final_action",
        workflow="GARAGE_CONVENTIONNE",
    )
    canonical = _canonical(
        f"http://{ALLOWED_HOST}/SinAuto_MCMA/expertise/gestiongarage/garageModifierValDevis",
        method="POST",
        content_type="application/x-www-form-urlencoded",
        body="",
    )
    assert evaluate_request(canonical, (rogue_contract,), ALLOWED_HOST) is Decision.DENY
