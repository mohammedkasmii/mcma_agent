"""
GET /events must be a plain request, not one that demands a `request` query
parameter.

Found during real browser E2E on Windows. `create_sse_endpoint`'s inner
function was declared `async def endpoint(request)` with no annotation, so
when it was registered via `app.add_api_route`, FastAPI could not recognise
`request` as the Starlette request and treated it as an ordinary function
argument -- which for a GET route means a required QUERY parameter. Every
EventSource connection got:

    HTTP 422 {"detail":[{"type":"missing","loc":["query","request"], ...}]}

so the stream never opened and the UI silently stopped refreshing. Adding
`request: Request` fixed it.

These tests go through the REAL registration path -- a real FastAPI app, the
real add_api_route call from mcma.app.api.app, a real HTTP request -- rather
than reading the function signature as text. A signature check would pass
against a differently-broken endpoint; only routing can tell us what FastAPI
actually decided the parameter was.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from mcma.app.sse import create_sse_endpoint
from sse_test_support import ACCOUNT_A, StubAuthorizer


class _Principal:
    user_id = "user-1"


@pytest.fixture()
def client(conn):
    """The same wiring mcma.app.api.app uses: create_sse_endpoint(...) handed
    to add_api_route at /events."""
    app = FastAPI()
    endpoint = create_sse_endpoint(
        conn, StubAuthorizer({ACCOUNT_A}), lambda request: _Principal()
    )
    app.add_api_route("/events", endpoint, methods=["GET"])
    return TestClient(app)


def _events_route(client):
    return next(r for r in client.app.routes if getattr(r, "path", None) == "/events")


def test_fastapi_does_not_treat_request_as_client_input(client):
    """The regression, stated as the thing that actually broke: FastAPI must
    not have decided `request` is a query parameter. Removing the `Request`
    annotation puts a required `request` field in this list and fails here."""
    route = _events_route(client)
    query_fields = [field.name for field in route.dependant.query_params]
    assert query_fields == [], f"/events must take no query parameters, got {query_fields}"
    assert "request" not in query_fields
    # And nothing moved into another input location instead.
    for location in (route.dependant.path_params, route.dependant.body_params):
        assert [field.name for field in location] == []


def test_fastapi_binds_the_starlette_request_itself(client):
    """The positive half: FastAPI recognised the parameter and will pass the
    real Request. Without the annotation this is None -- which is exactly why
    the endpoint could not read Last-Event-ID."""
    assert _events_route(client).dependant.request_param_name == "request"


def test_the_published_contract_declares_no_parameters(client):
    """What a client would be told the route expects. A `request` query
    parameter here would mean every EventSource connection is rejected as
    malformed before the handler runs."""
    schema = client.app.openapi()["paths"]["/events"]["get"]
    assert schema.get("parameters", []) == []
