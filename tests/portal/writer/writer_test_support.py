"""
INC-09B -- shared fakes/constants for tests/portal/writer/*. Deliberately
NOT named conftest.py (bare-module-name collision across tests/mock/
conftest.py and tests/portal/safety/conftest.py); deliberately
self-contained rather than importing test-support modules from other
directories -- established INC-06/07/08/09A convention.
"""

import asyncio
from decimal import Decimal
from pathlib import Path

from mcma.core.money import Money
from mcma.domain.values import RubriqueId
from mcma.portal.capabilities import LeaseInvalid
from mcma.portal.contracts import RouteContract
from mcma.portal.identity import ExpectedIdentity
from mcma.portal.writer import require_mcma_writer_account

FIXTURES_DIR = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "contracts"

ALLOWED_HOST = "127.0.0.1:8080"
SYNTHETIC_ACCOUNT_ID = "synthetic-account"


def mcma_writer_account(account_id: str = SYNTHETIC_ACCOUNT_ID):
    """MAMDA read-only enforcement, layer 3: every open_verified_writer()
    call in these tests must present an McmaWriterAccountContext whose
    account_id matches the SyntheticLeaseHandle it is paired with."""
    return require_mcma_writer_account(account_id, entity="MCMA", active=True)


MCMA_WRITER_ACCOUNT = mcma_writer_account()


def run_async(coro):
    return asyncio.run(coro)


def money(value: str) -> Money:
    return Money.of(Decimal(value))


def row_intent(rubrique_id: str, ht: str, tva: str, vetuste: str = "0.00"):
    from mcma.portal.writer import PortalRowIntent

    return PortalRowIntent(
        rubrique_id=RubriqueId(rubrique_id), ht=money(ht), tva=money(tva), vetuste=money(vetuste)
    )


# --------------------------------------------------------------------- #
# Reviewed contracts mirroring the mock's real routes
# --------------------------------------------------------------------- #

SEARCH_PAGE_CONTRACT = RouteContract(
    host=ALLOWED_HOST,
    route="/SinAuto_MCMA/expertise/frontexpert",
    method="GET",
    query_fields=frozenset(),
    content_type=None,
    body_fields=frozenset(),
    capability="read",
    operation_type="search_page",
    workflow=None,
)

SEARCH_LISTE_MISSIONS_CONTRACT = RouteContract(
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

NORMAL_ROW_WRITE_CONTRACT = RouteContract(
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

PEC_ROW_WRITE_CONTRACT = RouteContract(
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

NORMAL_READ_ROWS_CONTRACT = RouteContract(
    host=ALLOWED_HOST,
    route="/SinAuto_MCMA/expertise/gestionExpert/listeRapportDefDet",
    method="POST",
    query_fields=frozenset(),
    content_type="application/x-www-form-urlencoded",
    body_fields=frozenset(),
    capability="read",
    operation_type="read_rows",
    workflow="MODE_NORMAL",
)

PEC_READ_ROWS_CONTRACT = RouteContract(
    host=ALLOWED_HOST,
    route="/SinAuto_MCMA/expertise/gestiongarage/listeDevisDet",
    method="POST",
    query_fields=frozenset(),
    content_type="application/x-www-form-urlencoded",
    body_fields=frozenset(),
    capability="read",
    operation_type="read_rows",
    workflow="GARAGE_CONVENTIONNE",
)

PEC_NATIVE_RECALC_CONTRACT = RouteContract(
    host=ALLOWED_HOST,
    route="/_mock/pec/native_calculation",
    method="POST",
    query_fields=frozenset(),
    content_type="application/json",
    body_fields=frozenset({"total_ttc", "total_tva", "franchise", "vetuste", "remise", "part_resp", "simulate"}),
    capability="native_recalc",
    operation_type="native_recalc",
    workflow="GARAGE_CONVENTIONNE",
)

SHARED_ROW_WRITE_CONTRACT = RouteContract(
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
    workflow=None,  # shared/None -- must be rejected for a write contract
)

OTHER_WORKFLOW_ROW_WRITE_CONTRACT = RouteContract(
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
    workflow="GARAGE_CONVENTIONNE",  # the OTHER workflow, when opening a MODE_NORMAL writer
)

PERMANENTLY_BLOCKED_WRITE_CONTRACT = RouteContract(
    host=ALLOWED_HOST,
    route="/SinAuto_MCMA/expertise/gestiongarage/garageModifierValDevis",
    method="POST",
    query_fields=frozenset(),
    content_type="application/x-www-form-urlencoded",
    body_fields=frozenset(),
    capability="row_write",
    operation_type="edit_row",
    workflow="MODE_NORMAL",  # matches the plan under test in
    # test_permanently_blocked_write_contract_is_rejected_before_any_browser_context
    # -- must survive contracts_for_workflow's filter to reach the
    # permanently-blocked check at all.
)

def make_expected_identity(registration: str, id_sinistre: str) -> ExpectedIdentity:
    from mcma.domain.values import IdSinistre, RegistrationPlate

    return ExpectedIdentity(registration=RegistrationPlate(registration), id_sinistre=IdSinistre(id_sinistre))


# --------------------------------------------------------------------- #
# Fake Playwright objects -- no real browser anywhere in this file
# --------------------------------------------------------------------- #


class SyntheticLeaseHandle:
    def __init__(self, account_id="synthetic-account", valid=True):
        self.account_id = account_id
        self.valid = valid
        self.assert_valid_calls = 0

    async def assert_valid(self):
        self.assert_valid_calls += 1
        if not self.valid:
            raise LeaseInvalid(self.account_id)


class FakePage:
    """Records goto()/evaluate() calls; queued results are popped in
    order. locator()/expect_response() are exercised only by the real
    Chromium proofs (a real Page), never by these fake-based unit tests --
    open_verified_writer's construction sequence never calls them."""

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


class FailingNewPageContext(FakeContext):
    async def new_page(self):
        raise RuntimeError("page creation failed")


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
