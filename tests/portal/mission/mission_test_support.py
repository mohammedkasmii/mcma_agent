"""
INC-09A -- shared fakes/constants for tests/portal/mission/*. Deliberately
NOT named conftest.py and deliberately self-contained (own FakePage, not
imported from tests/portal/capabilities/capabilities_test_support.py):
two same-named bare modules across directories collide in sys.modules when
the whole suite runs together (fixed in INC-06/07/08 -- see those modules'
docstrings). A little duplication here is the safe trade-off.

No real Playwright browser is used by anything in this file.
"""

import asyncio

ALLOWED_HOST = "127.0.0.1:8080"


def run_async(coro):
    return asyncio.run(coro)


class FakePage:
    def __init__(self, evaluate_results=None, goto_results=None):
        self.goto_calls = []
        self.evaluate_calls = []
        self._evaluate_results = list(evaluate_results) if evaluate_results is not None else None
        self._goto_results = list(goto_results) if goto_results is not None else None

    async def goto(self, url, **kwargs):
        self.goto_calls.append(url)
        if self._goto_results:
            result = self._goto_results.pop(0)
            if isinstance(result, Exception):
                raise result

    async def evaluate(self, script, arg=None):
        self.evaluate_calls.append((script, arg))
        if self._evaluate_results is not None:
            if not self._evaluate_results:
                return None
            result = self._evaluate_results.pop(0)
            if isinstance(result, Exception):
                raise result
            return result
        return None
