"""Cross-contract end to end, loopback only. The REAL runner-side
RegistryHttpClient + NotificationOnboardingLifecycle talk to the REAL server
app (routes, service, migration, vault); only the visible browser login is a
fake. Proves the two halves agree on the wire."""

import asyncio
import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from api_test_support import MAMDA_OUJDA, NADOR, OUJDA, conn, csrf_headers, db_path  # noqa: F401
from mcma.app.workstation_runner.browser_gate import BrowserOperationGate
from mcma.app.workstation_runner.http_client import RegistryHttpClient
from mcma.app.workstation_runner.job_worker import JobPollingWorker
from mcma.app.workstation_runner.notification_onboarding import NotificationOnboardingLifecycle, OnboardingEvent
from mcma.persistence.db import open_database
from mcma.portal.sinauto_contracts import DEFAULT_SINAUTO_HOST
from mcma.portal.vault import load_and_verify_session
from test_notification_onboarding_api import MARKER, click, good_state, world  # noqa: F401


class AsgiTransport(httpx.BaseTransport):
    """Plays the verified-HTTPS hop in-process: forwards to the real ASGI app."""

    def __init__(self, app):
        self._client = TestClient(app, base_url="https://central.example.local", client=("203.0.113.9", 4000))

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        reply = self._client.request(request.method, request.url.raw_path.decode(), headers=dict(request.headers),
                                     content=request.read())
        return httpx.Response(reply.status_code, headers=dict(reply.headers), content=reply.content)


class FakeMaterial:
    def __init__(self, state):
        self._state, self.consumed = state, 0

    def consume_for_handoff(self):
        self.consumed += 1
        return self._state


def start_runner(world, login, events):
    client = RegistryHttpClient("https://central.example.local", transport=AsgiTransport(world["app"]))
    lifecycle = NotificationOnboardingLifecycle(
        client, login, gate=BrowserOperationGate(), is_ready=lambda: True, on_event=events.append,
        poll_interval_seconds=0.05, renew_interval_seconds=0.05, tick_seconds=0.02, upload_retry_delay_seconds=0.05,
    )
    worker = JobPollingWorker(lifecycle, world["secret"])
    worker.start()
    return worker


def wait_for(world, account, wanted, seconds=20.0):
    deadline = time.monotonic() + seconds
    state = None
    while time.monotonic() < deadline:
        state = world["employee"].get(f"/accounts/{account}/login-status").json()
        if state["state"] in wanted:
            return state
        time.sleep(0.05)
    raise AssertionError(f"timed out in state {state}")


@pytest.mark.parametrize("account", [OUJDA, MAMDA_OUJDA])
def test_click_to_connected_through_real_runner_client(world, account):
    material, events, closed = FakeMaterial(good_state()), [], []

    async def login(account_id, on_window_opened, timeout_seconds):
        try:
            assert account_id == account
            on_window_opened()
            await asyncio.sleep(0.2)                       # the employee signs in + OTP, directly in SinAuto
            return material
        finally:
            closed.append(account_id)

    assert click(world, account).status_code == 202
    worker = start_runner(world, login, events)
    try:
        seen = wait_for(world, account, {"SUCCEEDED", "FAILED", "EXPIRED", "CANCELLED"})
    finally:
        assert worker.stop(timeout=5.0)
    assert seen["state"] == "SUCCEEDED" and seen["outcome_code"] == "SESSION_STORED"
    assert material.consumed == 1 and closed == [account]           # one upload, window closed
    assert OnboardingEvent.SUCCEEDED in events
    accounts = {a["account_id"]: a for a in world["employee"].get("/accounts").json()["accounts"]}
    assert accounts[account]["connection_state"] == "CONNECTED"
    poller = open_database(world["conn"].execute("PRAGMA database_list").fetchone()[2])
    try:                                                            # the headless poller's own connection reads it back
        stored = json.loads(load_and_verify_session(poller, account, vault_dir=world["vault"], backend=world["backend"]))
    finally:
        poller.close()
    assert stored["cookies"][0]["value"] == MARKER
    assert all(MARKER.encode() not in p.read_bytes() for p in world["vault"].iterdir())
    assert world["conn"].execute("SELECT COUNT(*) FROM runner_account_capabilities WHERE account_id=?",
                                 (MAMDA_OUJDA,)).fetchone()[0] == 0


def test_window_closed_is_reported_specifically(world):
    events = []

    async def login(account_id, on_window_opened, timeout_seconds):
        on_window_opened()
        await asyncio.sleep(0.1)
        raise RuntimeError("TargetClosedError")               # whatever the portal helper raises

    click(world, NADOR)
    worker = start_runner(world, login, events)
    try:
        seen = wait_for(world, NADOR, {"SUCCEEDED", "FAILED", "EXPIRED", "CANCELLED"})
    finally:
        assert worker.stop(timeout=5.0)
    assert seen["state"] == "FAILED" and seen["outcome_code"] in {"INTERNAL_ERROR", "LOGIN_WINDOW_CLOSED"}
    assert world["conn"].execute("SELECT COUNT(*) FROM portal_sessions").fetchone()[0] == 0


def test_user_cancel_closes_the_runner_window(world):
    closed = []

    async def login(account_id, on_window_opened, timeout_seconds):
        try:
            on_window_opened()
            await asyncio.Event().wait()
        finally:
            closed.append(1)

    click(world, NADOR)
    worker = start_runner(world, login, [])
    try:
        wait_for(world, NADOR, {"WINDOW_OPENED", "WAITING_FOR_LOGIN"})
        world["employee"].post(f"/accounts/{NADOR}/login/cancel", headers=csrf_headers(world["csrf"]))
        seen = wait_for(world, NADOR, {"CANCELLED", "FAILED", "EXPIRED", "SUCCEEDED"})
    finally:
        assert worker.stop(timeout=5.0)
    assert seen["state"] == "CANCELLED" and closed == [1]


def test_existing_headless_poller_opens_the_newly_stored_session(world, monkeypatch):
    """No restart, no special path: poll_one_account on the poller's own
    connection loads the session the onboarding just stored (real vault code,
    real AES backend) and hands exactly that storage_state to its headless
    context."""
    from mcma.notifications import poller as poller_module

    seen = {}

    class Reader:
        async def observe_session_state(self):
            return "AUTHENTICATED"

        async def discover_notification_categories(self):
            return ()

        async def close(self):
            pass

    async def open_reader(browser, lease, contracts, allowed_host, *, context_options, portal_base):
        seen["storage_state"] = context_options["storage_state"]
        return Reader()

    monkeypatch.setattr(poller_module, "open_reader", open_reader)

    async def login(account_id, on_window_opened, timeout_seconds):
        on_window_opened()
        return FakeMaterial(good_state())

    click(world, OUJDA)
    worker = start_runner(world, login, [])
    try:
        assert wait_for(world, OUJDA, {"SUCCEEDED", "FAILED"})["state"] == "SUCCEEDED"
    finally:
        assert worker.stop(timeout=5.0)

    poller = open_database(world["conn"].execute("PRAGMA database_list").fetchone()[2])
    try:
        outcome = asyncio.run(poller_module.poll_one_account(
            poller, object(), OUJDA, (), instance_id="poller", allowed_host=DEFAULT_SINAUTO_HOST,
            vault_dir=world["vault"], crypto_backend=world["backend"], entity="MCMA",
        ))
    finally:
        poller.close()
    assert outcome != "NO_SESSION"
    assert seen["storage_state"]["cookies"][0]["value"] == MARKER
