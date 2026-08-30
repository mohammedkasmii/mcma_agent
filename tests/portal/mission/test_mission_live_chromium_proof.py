"""
INC-09A amendments -- isolated real-Playwright proof tests. These launch a
real headless Chromium against the INC-06 mock server, served for real on
loopback for the duration of each test. They run ONLY inside the existing
loopback-only isolated-CI mechanism: every test below is marked both
`egress_proof` (so local full-suite runs deselect it with
`-m "not egress_proof"`) and `requires_egress_isolation` (so
`testsupport/egress_guard.py`'s `pytest_runtest_setup` hook fails the test
AT SETUP, before any browser is launched, when structural isolation is not
confirmed -- no `--no-sandbox` fallback, no local escape hatch).

Every negative assertion below carries its positive control in the SAME
test, the SAME guarded context -- the INC-08 lesson: a "fails closed"
assertion proves nothing on its own if everything in that context would
fail regardless. The stub-level positive control for "both sections
present fails closed" lives in test_workflow_detection.py::
test_raises_indeterminate_when_both_present (the mock's own DEFAULT
rendering has both sections' DOM elements present, one merely hidden via
CSS -- exactly what that test exercises).

The mock server is served for real (uvicorn on 127.0.0.1) only because a
real browser needs a real socket to connect to; TestClient's in-process
ASGI transport cannot serve a real Chromium instance. Everything stays on
loopback; the production hostname is never resolved or contacted.
"""

import asyncio
import socket
import threading
import time

import pytest
import uvicorn

import mock_server
from mcma.domain.enums import RepairWorkflow
from mcma.domain.values import IdSinistre, RegistrationPlate
from mcma.portal.capabilities import SearchIdentifiers
from mcma.portal.identity import ExpectedIdentity, IdentityMismatch, verify_identity
from mcma.portal.mission import (
    MissionSelectionError,
    detect_observed_workflow,
    observe_identity,
    search_exactly_one,
)
from mcma.portal.session import open_guarded_context
from mission_test_support import (
    ALLOWED_HOST,
    MISSION_INDEX_CONTRACT,
    MISSION_INDEX_WORKFLOW_QUERY_CONTRACT,
    READ_LIST_MISSIONS_CONTRACT,
)

# ALLOWED_HOST is imported, never redefined here -- the CI run 33317487676
# lesson (INC-08): two independently-defined host literals silently
# diverging made every contract fail to match. PROOF_HOST/PROOF_PORT are
# derived FROM the single shared value, not the other way around.
PROOF_HOST, _proof_port_str = ALLOWED_HOST.split(":", 1)
PROOF_PORT = int(_proof_port_str)
BASE_URL = f"http://{ALLOWED_HOST}"

pytestmark = [pytest.mark.egress_proof, pytest.mark.requires_egress_isolation]


class _ServerThread(threading.Thread):
    def __init__(self, app, host, port):
        super().__init__(daemon=True)
        self._server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="warning"))

    def run(self):
        asyncio.run(self._server.serve())

    def stop(self):
        self._server.should_exit = True


@pytest.fixture()
def live_mock_server():
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
    try:
        yield BASE_URL
    finally:
        thread.stop()
        thread.join(timeout=5)
        mock_server.MOCK_STATE.clear()
        mock_server.MOCK_STATE.update(mock_server._initial_state())


# --------------------------------------------------------------------- #
# (a) Exactly-one search: zero-candidate negative, matching positive
# --------------------------------------------------------------------- #


def test_search_zero_candidates_fails_closed_with_matching_plate_as_positive_control(live_mock_server):
    asyncio.run(_search_zero_then_matching())


async def _search_zero_then_matching():
    from playwright.async_api import async_playwright

    # A guarded context installed with an EMPTY contract tuple denies
    # EVERYTHING, including the page load itself (CI run 33319654003) -- a
    # test cannot "opt out" of interception by declaring itself not about
    # the guard. This proof both navigates (needs MISSION_INDEX_CONTRACT)
    # and fetches listeMissions (needs READ_LIST_MISSIONS_CONTRACT).
    contracts = (MISSION_INDEX_CONTRACT, READ_LIST_MISSIONS_CONTRACT)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            context = await open_guarded_context(browser, contracts, ALLOWED_HOST)
            page = await context.new_page()
            await page.goto(f"{BASE_URL}/SinAuto_MCMA/expertise/gestionexpert/index")

            # Negative: a plate that does not exist in the mock's fixed data.
            with pytest.raises(MissionSelectionError) as exc_info:
                await search_exactly_one(page, ALLOWED_HOST, SearchIdentifiers(matricule="00000-A-00"))
            assert exc_info.value.count == 0

            # Positive control: the SAME search flow, SAME context, with the
            # mock's real plate, succeeds with exactly one candidate.
            candidate = await search_exactly_one(
                page, ALLOWED_HOST, SearchIdentifiers(matricule="34602-B-7")
            )
            assert candidate.id_mission == 532805

            await context.close()
        finally:
            await browser.close()


# --------------------------------------------------------------------- #
# (b) Workflow detection: both directions in the same context
# --------------------------------------------------------------------- #


def test_workflow_detection_returns_normal_and_conventionne_correctly(live_mock_server):
    asyncio.run(_detect_both_directions())


async def _detect_both_directions():
    from playwright.async_api import async_playwright

    # Both ?workflow=normal and ?workflow=conventionne canonicalize to the
    # SAME query_fields={"workflow"} shape (evaluate_request compares field
    # NAMES, not values) -- one contract covers both navigations below.
    contracts = (MISSION_INDEX_WORKFLOW_QUERY_CONTRACT,)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            context = await open_guarded_context(browser, contracts, ALLOWED_HOST)
            page = await context.new_page()

            await page.goto(f"{BASE_URL}/SinAuto_MCMA/expertise/gestionexpert/index?workflow=normal")
            assert await detect_observed_workflow(page) is RepairWorkflow.MODE_NORMAL

            await page.goto(
                f"{BASE_URL}/SinAuto_MCMA/expertise/gestionexpert/index?workflow=conventionne"
            )
            assert await detect_observed_workflow(page) is RepairWorkflow.GARAGE_CONVENTIONNE

            await context.close()
        finally:
            await browser.close()


# --------------------------------------------------------------------- #
# (c) Identity: matching positive, mismatched negative, same context
# --------------------------------------------------------------------- #


def test_identity_verifies_on_match_and_fails_closed_on_mismatch(live_mock_server):
    asyncio.run(_identity_match_then_mismatch())


async def _identity_match_then_mismatch():
    from playwright.async_api import async_playwright

    contracts = (MISSION_INDEX_CONTRACT,)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            context = await open_guarded_context(browser, contracts, ALLOWED_HOST)
            page = await context.new_page()
            await page.goto(f"{BASE_URL}/SinAuto_MCMA/expertise/gestionexpert/index")

            observed = await observe_identity(page)
            assert observed.registration is not None
            assert observed.id_sinistre is not None

            # Positive: expected identity matches exactly what the real page exposes.
            matching_expected = ExpectedIdentity(
                registration=RegistrationPlate("34602-B-7"), id_sinistre=IdSinistre("534660")
            )
            verify_identity(matching_expected, observed)  # must not raise

            # Negative: same observed page, a wrong id_sinistre.
            mismatched_expected = ExpectedIdentity(
                registration=RegistrationPlate("34602-B-7"), id_sinistre=IdSinistre("000000")
            )
            with pytest.raises(IdentityMismatch) as exc_info:
                verify_identity(mismatched_expected, observed)
            assert exc_info.value.field == "id_sinistre"

            await context.close()
        finally:
            await browser.close()
