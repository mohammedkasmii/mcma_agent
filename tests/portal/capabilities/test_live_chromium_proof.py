"""
INC-08 amendment #7 -- isolated real-Playwright proof tests. These launch a
real headless Chromium against the INC-06 mock server, served for real on
loopback for the duration of each test. They run ONLY inside the existing
loopback-only isolated-CI mechanism: every test below is marked both
`egress_proof` (so local full-suite runs deselect it with
`-m "not egress_proof"`, same convention as tests/safety/test_egress_proof.py)
and `requires_egress_isolation` (so `testsupport/egress_guard.py`'s
`pytest_runtest_setup` hook fails the test AT SETUP, before any browser is
launched, when structural isolation is not confirmed -- no `--no-sandbox`
fallback, no local escape hatch).

The mock server is served for real (uvicorn on 127.0.0.1) only because a
real browser needs a real socket to connect to; TestClient's in-process ASGI
transport cannot serve a real Chromium instance. Everything stays on
loopback; the production hostname is never resolved or contacted.
"""

import asyncio
import socket
import threading
import time

import pytest
import uvicorn

import mock_server
from capabilities_test_support import (
    ALLOWED_HOST,
    AUTH_LOGIN_CONTRACT,
    AUTH_LOGIN_PAGE_CONTRACT,
    READ_NORMAL_ROWS_CONTRACT,
    READ_SEARCH_PAGE_CONTRACT,
    SyntheticLeaseHandle,
)
from mcma.portal.capabilities import SessionMaterial, open_login_session, open_reader
from mcma.portal.session import open_guarded_context

# CI run 33317487676 regression: this file previously defined its OWN
# PROOF_HOST/PROOF_PORT/ALLOWED_HOST literal, independent of the host every
# contract in capabilities_test_support is built for. The two host values
# silently diverged (:8080 vs :18765), so no contract could ever match a
# real request and every one of these 5 tests failed unconditionally. The
# live server MUST be served on exactly the same host:port ALLOWED_HOST
# names -- ALLOWED_HOST is imported, never redefined here (see
# test_host_consistency.py for the permanent regression test).
PROOF_HOST, _proof_port_str = ALLOWED_HOST.split(":", 1)
PROOF_PORT = int(_proof_port_str)
BASE_URL = f"http://{ALLOWED_HOST}"

pytestmark = [pytest.mark.egress_proof, pytest.mark.requires_egress_isolation]


class _ServerThread(threading.Thread):
    def __init__(self, app, host, port):
        super().__init__(daemon=True)
        self._config = uvicorn.Config(app, host=host, port=port, log_level="warning")
        self._server = uvicorn.Server(self._config)

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


def test_open_reader_creates_guarded_context_and_performs_real_allowed_read(live_mock_server):
    asyncio.run(_open_reader_real_read())


async def _open_reader_real_read():
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            reader = await open_reader(
                browser,
                SyntheticLeaseHandle(),
                (READ_NORMAL_ROWS_CONTRACT, READ_SEARCH_PAGE_CONTRACT),
                ALLOWED_HOST,
            )
            try:
                from mcma.domain.enums import RepairWorkflow

                rows = await reader.read_rows(RepairWorkflow.MODE_NORMAL)
                assert rows == ()
            finally:
                await reader.close()
        finally:
            await browser.close()


def test_login_capability_observes_synthetic_marker_and_returns_redacted_material(live_mock_server):
    asyncio.run(_login_flow(live_mock_server))


async def _login_flow(base_url):
    import httpx
    from playwright.async_api import async_playwright

    # Simulate "the human already logged in" out of band -- LoginCapability
    # itself never fills credentials (amendment #6); it only navigates to
    # the contract-supplied login-page route and polls fixed markers.
    async with httpx.AsyncClient() as client:
        await client.post(f"{base_url}/SinAuto_MCMA/front/Login/login")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            login = await open_login_session(
                browser,
                "synthetic-account",
                (AUTH_LOGIN_CONTRACT, AUTH_LOGIN_PAGE_CONTRACT),
                ALLOWED_HOST,
            )
            try:
                material = await login.perform_manual_login(
                    poll_interval_seconds=0.2, timeout_seconds=10
                )
                assert isinstance(material, SessionMaterial)
                assert "synthetic-account" in repr(material)
            finally:
                await login.close()
        finally:
            await browser.close()


def test_final_endpoint_request_is_aborted_before_reaching_the_mock_sentinel(live_mock_server):
    asyncio.run(_final_endpoint_aborted())


async def _final_endpoint_aborted():
    import httpx
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            context = await open_guarded_context(
                browser, (READ_SEARCH_PAGE_CONTRACT,), ALLOWED_HOST
            )
            page = await context.new_page()
            # Establish a same-origin document FIRST via one allowed GET.
            # A page left at about:blank has an opaque/null origin, and a
            # fetch() from there to any host -- allowed or not -- is
            # cross-origin and rejected by the browser's own CORS policy
            # (the mock never sends CORS headers), which would make this
            # "blocked" outcome prove nothing about the interception guard.
            # Navigating first removes that confound: any block observed
            # below is attributable to the guard, not incidental CORS.
            await page.goto(f"{BASE_URL}{READ_SEARCH_PAGE_CONTRACT.route}")
            outcome = await page.evaluate(
                """(url) => fetch(url, {method: 'POST'}).then(() => 'reached', () => 'blocked')""",
                f"{BASE_URL}/SinAuto_MCMA/expertise/gestiongarage/garageModifierValDevis",
            )
            assert outcome == "blocked"
            await context.close()
        finally:
            await browser.close()

    async with httpx.AsyncClient() as client:
        state = (await client.get(f"{BASE_URL}/_mock/state")).json()
    assert state["observability"]["final_endpoint_hits"]["garageModifierValDevis"] == 0


def test_unknown_request_is_aborted(live_mock_server):
    asyncio.run(_unknown_request_aborted())


async def _unknown_request_aborted():
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            context = await open_guarded_context(
                browser, (READ_SEARCH_PAGE_CONTRACT,), ALLOWED_HOST
            )
            page = await context.new_page()
            # Same-origin document first -- see the comment in
            # _final_endpoint_aborted for why this rules out a CORS
            # confound rather than proving the interception guard.
            await page.goto(f"{BASE_URL}{READ_SEARCH_PAGE_CONTRACT.route}")
            outcome = await page.evaluate(
                """(url) => fetch(url).then(() => 'reached', () => 'blocked')""",
                f"{BASE_URL}/SinAuto_MCMA/expertise/gestionExpert/totallyUnknownRoute",
            )
            assert outcome == "blocked"
            await context.close()
        finally:
            await browser.close()


def test_context_level_protection_covers_a_newly_created_page(live_mock_server):
    asyncio.run(_new_page_is_covered())


async def _new_page_is_covered():
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            context = await open_guarded_context(
                browser, (READ_SEARCH_PAGE_CONTRACT,), ALLOWED_HOST
            )
            first_page = await context.new_page()
            await first_page.goto(f"{BASE_URL}{READ_SEARCH_PAGE_CONTRACT.route}")

            # A SECOND page, opened after the guard was installed and after
            # the first page was already in use -- proves the guard is
            # context-level, not attached to one specific page. Same-origin
            # navigation first, for the same CORS-confound reason as above.
            second_page = await context.new_page()
            await second_page.goto(f"{BASE_URL}{READ_SEARCH_PAGE_CONTRACT.route}")
            outcome = await second_page.evaluate(
                """(url) => fetch(url, {method: 'POST'}).then(() => 'reached', () => 'blocked')""",
                f"{BASE_URL}/SinAuto_MCMA/expertise/gestiongarage/garageModifierValDevis",
            )
            assert outcome == "blocked"
            await context.close()
        finally:
            await browser.close()
