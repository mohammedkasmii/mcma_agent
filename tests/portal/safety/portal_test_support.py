"""
INC-07 -- shared fakes/constants for tests/portal/safety/*. Deliberately NOT
named conftest.py: pytest auto-imports every conftest.py it discovers under
the bare module name "conftest", and this repo also has tests/mock/
conftest.py -- two same-named bare modules loaded in one session collide in
sys.modules. A uniquely named support module avoids that entirely.

FakeContext/FakeRoute/FakeWebSocketRoute/FakeRequest implement exactly the
async Playwright methods mcma.portal.interception calls
(route/route_web_socket/abort/continue_/fulfill/close), recording every
call. No real Playwright browser is launched anywhere in this test package
-- these are hand-written stubs, not a live BrowserContext.
"""

import asyncio
from pathlib import Path

FIXTURES_DIR = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "contracts"


def run_async(coro):
    """Drive a coroutine from a plain sync test function -- no
    pytest-asyncio dependency needed."""
    return asyncio.run(coro)


class FakeRequest:
    def __init__(self, url, method="GET", headers=None, post_data=None):
        self.url = url
        self.method = method
        self._headers = headers or {}
        self.post_data = post_data

    @property
    def headers(self):
        return self._headers


class FakeRequestHeadersRaise:
    """Simulates a Playwright object whose property access itself fails --
    proves descriptor-extraction failure aborts, not just a bad value."""

    url = "http://127.0.0.1:8080/x"
    method = "GET"
    post_data = None

    @property
    def headers(self):
        raise RuntimeError("boom")


class FakeRoute:
    def __init__(self, request):
        self.request = request
        self.aborted = 0
        self.continued = 0
        self.fulfilled = 0

    async def abort(self, error_code=None):
        self.aborted += 1

    async def continue_(self, **kwargs):
        self.continued += 1

    async def fulfill(self, **kwargs):
        self.fulfilled += 1


class FakeWebSocketRoute:
    def __init__(self):
        self.closed = 0

    async def close(self, **kwargs):
        self.closed += 1


class FakeContext:
    def __init__(self):
        self.route_calls = []
        self.ws_route_calls = []
        self.closed = 0

    async def route(self, pattern, handler):
        self.route_calls.append((pattern, handler))

    async def route_web_socket(self, pattern, handler):
        self.ws_route_calls.append((pattern, handler))

    async def close(self, **kwargs):
        self.closed += 1


class FailingWebSocketInstallContext(FakeContext):
    """route() succeeds; route_web_socket() fails -- proves a partially
    guarded context is closed, never left usable."""

    async def route_web_socket(self, pattern, handler):
        raise RuntimeError("websocket route installation failed")


class FailingHttpInstallContext(FakeContext):
    """route() itself fails -- the very first installation step."""

    async def route(self, pattern, handler):
        raise RuntimeError("http route installation failed")
