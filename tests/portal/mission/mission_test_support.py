"""
INC-09A -- shared fakes/constants for tests/portal/mission/*. Deliberately
NOT named conftest.py and deliberately self-contained (own FakePage, own
RouteContract constants -- not imported from tests/portal/capabilities/
capabilities_test_support.py): two same-named bare modules across
directories collide in sys.modules when the whole suite runs together
(fixed in INC-06/07/08 -- see those modules' docstrings). A little
duplication here is the safe trade-off.

No real Playwright browser is used by anything in this file.

CI run 33319654003 lesson: a guarded context installed with an EMPTY
contract tuple denies EVERYTHING, including the page load itself -- there
is no way for a test to "opt out" of interception by declaring the test
isn't about the guard. Any test that navigates or fetches inside a guarded
context needs a real, exactly-matching contract. The two mission-page
contracts below exist for exactly that reason.
"""

import asyncio

from mcma.portal.contracts import RouteContract

ALLOWED_HOST = "127.0.0.1:8080"


def run_async(coro):
    return asyncio.run(coro)


# The bare mission-page GET (no query string). See
# tests/fixtures/contracts/mission_index_navigation_mock_only.json for why
# this is classified MOCK_ONLY rather than confirmed live evidence.
MISSION_INDEX_CONTRACT = RouteContract(
    host=ALLOWED_HOST,
    route="/SinAuto_MCMA/expertise/gestionexpert/index",
    method="GET",
    query_fields=frozenset(),
    content_type=None,
    body_fields=frozenset(),
    capability="read",
    operation_type="mission_page",
    workflow=None,
)

# The SAME route with ?workflow=... -- a DIFFERENT canonical request
# (evaluate_request compares query_fields by exact set equality), so it
# needs its own contract. See
# tests/fixtures/contracts/mission_workflow_query_mock_only.json.
MISSION_INDEX_WORKFLOW_QUERY_CONTRACT = RouteContract(
    host=ALLOWED_HOST,
    route="/SinAuto_MCMA/expertise/gestionexpert/index",
    method="GET",
    query_fields=frozenset({"workflow"}),
    content_type=None,
    body_fields=frozenset(),
    capability="read",
    operation_type="mission_page_workflow_probe",
    workflow=None,
)

READ_LIST_MISSIONS_CONTRACT = RouteContract(
    host=ALLOWED_HOST,
    route="/SinAuto_MCMA/expertise/FrontExpert/listeMissions",
    method="POST",
    query_fields=frozenset(),
    content_type="application/x-www-form-urlencoded",
    body_fields=frozenset({"Matricule", "ReferenceCie"}),
    capability="read",
    operation_type="search",
    workflow=None,
)


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
