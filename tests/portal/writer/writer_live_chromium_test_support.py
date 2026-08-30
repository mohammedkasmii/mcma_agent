"""
INC-09B -- shared live-mock-server fixture for tests/portal/writer/*_live_
chromium_proof.py. Mirrors tests/portal/mission/test_mission_live_chromium_
proof.py's own _ServerThread/live_mock_server pattern exactly (a proven,
already-CI-green mechanism) -- deliberately duplicated rather than
imported, per this project's established bounded-duplication convention.

Every real-Chromium test in this package is marked both `egress_proof` and
`requires_egress_isolation` at module level via `pytestmark` in each file.
"""

import asyncio
import socket
import threading
import time

import pytest

import mock_server

ALLOWED_HOST = "127.0.0.1:8080"
_HOST, _PORT_STR = ALLOWED_HOST.split(":", 1)
PROOF_HOST = _HOST
PROOF_PORT = int(_PORT_STR)
BASE_URL = f"http://{ALLOWED_HOST}"


def run_async(coro):
    return asyncio.run(coro)


class _ServerThread(threading.Thread):
    def __init__(self, app, host, port):
        super().__init__(daemon=True)
        import uvicorn

        self._server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="warning"))

    def run(self):
        asyncio.run(self._server.serve())

    def stop(self):
        self._server.should_exit = True


def start_live_mock_server():
    mock_server.MOCK_STATE.clear()
    mock_server.MOCK_STATE.update(mock_server._initial_state())
    thread = _ServerThread(mock_server.app, PROOF_HOST, PROOF_PORT)
    thread.start()
    for _ in range(50):
        try:
            with socket.create_connection((PROOF_HOST, PROOF_PORT), timeout=0.2):
                break
        except OSError:
            time.sleep(0.1)
    else:  # pragma: no cover - defensive
        raise RuntimeError("live mock server did not start in time")
    return thread


def stop_live_mock_server(thread):
    thread.stop()
    thread.join(timeout=5)
    mock_server.MOCK_STATE.clear()
    mock_server.MOCK_STATE.update(mock_server._initial_state())


@pytest.fixture()
def live_mock_server():
    thread = start_live_mock_server()
    try:
        yield BASE_URL
    finally:
        stop_live_mock_server(thread)
