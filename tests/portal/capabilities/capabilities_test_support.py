"""
INC-08 -- shared fakes/constants for tests/portal/capabilities/*. Deliberately
NOT named conftest.py and deliberately self-contained (not importing from
tests/portal/safety/portal_test_support.py): two same-named bare modules
across directories collide in sys.modules when the whole suite runs together
(fixed once already in INC-07/INC-06 -- see those modules' docstrings), and a
cross-directory bare import of a same-purpose-but-different-file module would
reintroduce a variant of the same fragility. A little duplication here is the
safe trade-off.

No real Playwright browser is used by anything in this file -- these are
hand-written stubs.
"""

import asyncio
from pathlib import Path

from mcma.portal.contracts import RouteContract

FIXTURES_DIR = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "contracts"

ALLOWED_HOST = "127.0.0.1:8080"


def run_async(coro):
    return asyncio.run(coro)


# --------------------------------------------------------------------- #
# Sample reviewed contracts (mirrors the INC-06 mock's real routes)
# --------------------------------------------------------------------- #

AUTH_LOGIN_CONTRACT = RouteContract(
    host=ALLOWED_HOST,
    route="/SinAuto_MCMA/front/Login/login",
    method="POST",
    query_fields=frozenset(),
    content_type="application/x-www-form-urlencoded",
    body_fields=frozenset(),
    capability="auth",
    operation_type="login",
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

READ_NORMAL_ROWS_CONTRACT = RouteContract(
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

READ_PEC_ROWS_CONTRACT = RouteContract(
    host=ALLOWED_HOST,
    route="/SinAuto_MCMA/expertise/gestiongarage/listeDevisDet",
    method="POST",
    query_fields=frozenset(),
    content_type="application/x-www-form-urlencoded",
    body_fields=frozenset(),
    capability="read",
    operation_type="list_rows",
    workflow="GARAGE_CONVENTIONNE",
)

ROGUE_ROW_WRITE_CONTRACT = RouteContract(
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

ROGUE_FINAL_LABELED_AUTH_CONTRACT = RouteContract(
    host=ALLOWED_HOST,
    route="/SinAuto_MCMA/expertise/gestiongarage/garageModifierValDevis",
    method="POST",
    query_fields=frozenset(),
    content_type="application/x-www-form-urlencoded",
    body_fields=frozenset(),
    capability="auth",
    operation_type="login",
    workflow=None,
)


# --------------------------------------------------------------------- #
# Fake Playwright objects (no real browser anywhere in this file)
# --------------------------------------------------------------------- #


class FakeRequest:
    def __init__(self, url, method="GET", headers=None, post_data=None):
        self.url = url
        self.method = method
        self._headers = headers or {}
        self.post_data = post_data

    @property
    def headers(self):
        return self._headers


class FakeRoute:
    def __init__(self, request):
        self.request = request
        self.aborted = 0
        self.continued = 0

    async def abort(self, error_code=None):
        self.aborted += 1

    async def continue_(self, **kwargs):
        self.continued += 1


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


class FakeContext:
    def __init__(self, page_factory=None):
        self.route_calls = []
        self.ws_route_calls = []
        self.closed_count = 0
        self.pages_created = []
        self._page_factory = page_factory or FakePage
        self.storage_state_result = {"cookies": [], "origins": []}

    async def route(self, pattern, handler):
        self.route_calls.append((pattern, handler))

    async def route_web_socket(self, pattern, handler):
        self.ws_route_calls.append((pattern, handler))

    async def close(self, **kwargs):
        self.closed_count += 1

    async def new_page(self):
        page = self._page_factory()
        self.pages_created.append(page)
        return page

    async def storage_state(self):
        return self.storage_state_result


class FailingNewPageContext(FakeContext):
    async def new_page(self):
        raise RuntimeError("page creation failed")


class FailingWebSocketInstallContext(FakeContext):
    async def route_web_socket(self, pattern, handler):
        raise RuntimeError("websocket route installation failed")


class FakeBrowser:
    def __init__(self, context_factory=None):
        self._context_factory = context_factory or FakeContext
        self.new_context_calls = []
        self.contexts_created = []

    async def new_context(self, **options):
        self.new_context_calls.append(options)
        context = self._context_factory()
        self.contexts_created.append(context)
        return context


class FailingNewContextBrowser:
    async def new_context(self, **options):
        raise RuntimeError("new_context failed")


class SyntheticLeaseHandle:
    def __init__(self, account_id="synthetic-account", valid=True):
        self.account_id = account_id
        self.valid = valid
        self.assert_valid_calls = 0

    async def assert_valid(self):
        self.assert_valid_calls += 1
        if not self.valid:
            from mcma.portal.capabilities import LeaseInvalid

            raise LeaseInvalid(self.account_id)


class NotALeaseHandle:
    """Does not satisfy the LeaseHandle protocol at all (no assert_valid)."""

    def __init__(self):
        self.account_id = "not-a-lease"
