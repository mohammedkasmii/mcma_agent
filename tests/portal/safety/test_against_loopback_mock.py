"""
INC-07 amendment / constraint #13 -- tests use only the loopback fake portal
from INC-06 (mock_server.py, reached in-process via FastAPI TestClient).
Nothing here resolves or contacts a production hostname; "evil.example.com"
in test_route_contracts.py is never actually dialed, only compared as a
string inside canonicalize_request/evaluate_request.
"""

from fastapi.testclient import TestClient

import mock_server
from mcma.portal.canonical import canonicalize_request
from mcma.portal.contracts import Decision, RouteContract, evaluate_request

ALLOWED_HOST = "127.0.0.1:8080"

REAL_LIST_ROWS_CONTRACT = RouteContract(
    host=ALLOWED_HOST,
    route="/SinAuto_MCMA/expertise/gestionExpert/listeRapportDefDet",
    method="POST",
    query_fields=frozenset(),
    content_type="application/x-www-form-urlencoded",
    body_fields=frozenset(),
    capability="read",
    operation_type="list_rows",
    workflow="MODE_NORMAL",
)


def test_allowed_contract_matches_a_route_the_mock_genuinely_serves():
    canonical = canonicalize_request(
        raw_url=f"http://{ALLOWED_HOST}{REAL_LIST_ROWS_CONTRACT.route}",
        raw_method="POST",
        raw_content_type="application/x-www-form-urlencoded",
        raw_body="",
    )
    assert canonical is not None
    assert evaluate_request(canonical, (REAL_LIST_ROWS_CONTRACT,), ALLOWED_HOST) is Decision.ALLOW

    with TestClient(mock_server.app) as client:
        client.post("/_mock/reset")
        response = client.post(REAL_LIST_ROWS_CONTRACT.route)
        assert response.status_code == 200
        assert response.json()["state"] == "success"
        client.post("/_mock/reset")


def test_final_endpoint_route_is_denied_even_though_the_mock_responds():
    """The mock itself always answers (it is a sentinel, INC-06); the
    interception layer must deny the request before it would ever reach a
    real portal regardless of what a mock or the real host would answer."""
    route = mock_server.FINAL_ENDPOINT_ROUTES["garageModifierValDevis"]
    canonical = canonicalize_request(
        raw_url=f"http://{ALLOWED_HOST}{route}", raw_method="POST",
        raw_content_type="application/x-www-form-urlencoded", raw_body="",
    )
    assert canonical is not None
    assert evaluate_request(canonical, (), ALLOWED_HOST) is Decision.DENY
