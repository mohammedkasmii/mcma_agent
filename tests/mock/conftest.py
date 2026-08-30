"""
INC-06 — shared pytest fixtures for the extended offline mock portal
(mock_server.py).

The mock is exercised only through FastAPI's TestClient (ASGI transport, no
real socket) — safe under the repo-wide egress lock (`--disable-socket
--allow-hosts=127.0.0.1,::1`). No test in this package may open a real
network connection.

Plain constants/helpers live in mock_test_support.py, not here — see that
file's docstring for why (a bare "conftest" import would collide with
tests/portal/safety/conftest.py in the same test session).
"""

import pytest
from fastapi.testclient import TestClient

import mock_server


@pytest.fixture()
def client():
    with TestClient(mock_server.app) as c:
        c.post("/_mock/reset")
        yield c
        c.post("/_mock/reset")
