"""
The getAlerte request, judged by the interceptor that actually guards it.

These go through canonicalize_request + evaluate_request -- the same two
functions the live route handler calls -- rather than inspecting the
contract's fields. The bug this covers was invisible to a field-level
test: the contract was well-formed, the request was well-formed, and the
two simply did not match, so every real notification read was denied by
our own default-deny guard while discovery kept working.

Synthetic host and codes throughout.
"""

from __future__ import annotations

import pytest

from mcma.portal.canonical import canonicalize_request
from mcma.portal.contracts import Decision, evaluate_request
from mcma.portal.sinauto_contracts import (
    NOTIFICATION_BODY_FIELDS,
    notification_contracts,
    portal_base_for,
)

HOST = "sinauto.mamda-mcma.ma"
CODE = "11111111-2222-4333-8444-555555555555"

# Exactly what ReadCapability sends, including the charset parameter.
CONTENT_TYPE = "application/x-www-form-urlencoded; charset=UTF-8"
BODY = (
    "length=-1&start=0&iDisplayLength=-1&iDisplayStart=0"
    "&rows=999999&limit=999999&page=1&draw=1"
)


def _route(entity: str = "MCMA", code: str = CODE) -> str:
    return (
        f"https://{HOST}{portal_base_for(entity)}"
        f"/expertise/notification/getAlerte/CodeAlerte/{code}"
    )


def _decide(entity="MCMA", *, url=None, content_type=CONTENT_TYPE, body=BODY, method="POST") -> Decision:
    contracts = notification_contracts(HOST, (CODE,), entity)
    canonical = canonicalize_request(
        raw_url=url or _route(entity),
        raw_method=method,
        raw_content_type=content_type,
        raw_body=body,
    )
    if canonical is None:
        return Decision.DENY
    return evaluate_request(canonical, contracts, HOST)


def test_the_real_mcma_request_is_allowed():
    """The regression. Before the contract declared content_type and
    body_fields, this was DENY -- which is why eight discovered
    categories all read FAILED with rows_seen=None."""
    assert _decide("MCMA") is Decision.ALLOW


def test_the_real_mamda_request_is_allowed():
    assert _decide("MAMDA") is Decision.ALLOW


def test_an_mcma_route_is_denied_by_a_mamda_reader():
    """The two applications share a host under different bases."""
    contracts = notification_contracts(HOST, (CODE,), "MAMDA")
    canonical = canonicalize_request(
        raw_url=_route("MCMA"), raw_method="POST",
        raw_content_type=CONTENT_TYPE, raw_body=BODY,
    )
    assert evaluate_request(canonical, contracts, HOST) is Decision.DENY


def test_a_missing_body_field_is_denied():
    partial = "&".join(
        part for part in BODY.split("&") if not part.startswith("draw=")
    )
    assert _decide(body=partial) is Decision.DENY


def test_an_extra_body_field_is_denied():
    assert _decide(body=BODY + "&search=x") is Decision.DENY


def test_an_empty_body_is_denied():
    assert _decide(body="") is Decision.DENY


def test_the_wrong_content_type_is_denied():
    assert _decide(content_type="application/json") is Decision.DENY
    assert _decide(content_type=None, body=None) is Decision.DENY


def test_an_unreviewed_category_code_is_denied():
    """Contracts are installed per code: the portal cannot widen the set
    of categories a poll may read by returning another one."""
    assert _decide(url=_route(code="00000000-0000-0000-0000-000000000000")) is Decision.DENY


def test_a_different_route_on_the_same_host_is_denied():
    assert (
        _decide(url=f"https://{HOST}/SinAuto_MCMA/expertise/notification/supprimer/{CODE}")
        is Decision.DENY
    )


def test_another_host_is_denied():
    assert (
        _decide(url=f"https://evil.example.com/SinAuto_MCMA/expertise/notification/getAlerte/CodeAlerte/{CODE}")
        is Decision.DENY
    )


def test_the_wrong_method_is_denied():
    assert _decide(method="GET", content_type=None, body=None) is Decision.DENY


@pytest.mark.parametrize("entity", ["MCMA", "MAMDA"])
def test_the_contract_declares_the_eight_reviewed_fields(entity):
    contract = next(
        c for c in notification_contracts(HOST, (CODE,), entity) if c.method == "POST"
    )
    assert contract.content_type == "application/x-www-form-urlencoded"
    assert contract.body_fields == frozenset(NOTIFICATION_BODY_FIELDS)
    assert len(NOTIFICATION_BODY_FIELDS) == 8


def test_the_request_payload_and_the_contract_cannot_drift():
    """The reader builds its body from the contract's own field tuple, so
    adding a field in one place without the other is impossible rather
    than merely discouraged."""
    from mcma.portal.capabilities import _NOTIFICATION_FULL_DATASET_PAYLOAD

    assert tuple(_NOTIFICATION_FULL_DATASET_PAYLOAD) == NOTIFICATION_BODY_FIELDS
    # And the body those values produce is the one the contract allows.
    assert set(_NOTIFICATION_FULL_DATASET_PAYLOAD) == set(
        part.split("=")[0] for part in BODY.split("&")
    )


def test_the_landing_page_contract_is_still_a_bodyless_get():
    contract = next(
        c for c in notification_contracts(HOST, (CODE,), "MCMA") if c.method == "GET"
    )
    assert contract.content_type is None
    assert contract.body_fields == frozenset()
