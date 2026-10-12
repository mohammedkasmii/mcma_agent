"""End-to-end (runner side) through the REAL RegistryHttpClient over an
httpx.MockTransport that plays the server, the real lifecycle and the real
thread wrapper; only the browser login is fake. Loopback/no network."""

import asyncio
import json
import logging
import threading

import httpx

from mcma.app.workstation_runner.browser_gate import BrowserOperationGate
from mcma.app.workstation_runner.http_client import RegistryHttpClient
from mcma.app.workstation_runner.job_worker import JobPollingWorker
from mcma.app.workstation_runner.notification_onboarding import NotificationOnboardingLifecycle, OnboardingEvent

SECRET = "mcma_rs_" + "s" * 40
TOKEN = "mcma_ot_" + "t" * 40
REQUEST_ID = "c" * 32
MARKER = "E2E-COOKIE-SECRET-MARKER"
STATE = {"cookies": [{"name": "sid", "value": MARKER, "domain": "sinauto.example", "path": "/"}], "origins": []}


class FakeServer:
    def __init__(self, account_id="acct-mamda-nador"):
        self.account_id = account_id
        self.pending = True
        self.requests: list = []
        self.completed_bodies: list = []
        self.cancel_after_renews = None
        self.done = threading.Event()

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        body = json.loads(request.read() or b"{}")
        self.requests.append((path, request.headers.get("authorization"), body))
        if request.headers.get("authorization") != f"Bearer {SECRET}":
            return httpx.Response(401, json={"error": "RUNNER_UNAUTHENTICATED"})
        if path == "/runner/notification-onboarding/claim":
            if not self.pending:
                return httpx.Response(204)
            self.pending = False
            return httpx.Response(200, json={
                "request_id": REQUEST_ID, "account_id": self.account_id, "generation": 1, "claim_token": TOKEN,
                "lease_expires_at": "2026-01-01T00:01:00+00:00", "expires_at": "2026-01-01T00:05:00+00:00",
                "server_time": "2026-01-01T00:00:00+00:00",
            })
        if path.endswith("/renew"):
            renews = sum(1 for p, _, _ in self.requests if p.endswith("/renew"))
            cancel = self.cancel_after_renews is not None and renews > self.cancel_after_renews
            return httpx.Response(200, json={"lease_expires_at": "t", "server_time": "t", "cancel_requested": cancel})
        if path.endswith("/complete"):
            self.completed_bodies.append(body)
            self.done.set()
            return httpx.Response(200, json={"status": "SUCCEEDED", "server_time": "t"})
        if path.endswith("/fail"):
            self.done.set()
            return httpx.Response(200, json={"status": "FAILED" if body["reason_code"] != "CANCELLED" else "CANCELLED",
                                             "server_time": "t"})
        return httpx.Response(404, json={"error": "NOPE"})


class Material:
    def __init__(self):
        self.consumed = 0

    def consume_for_handoff(self):
        self.consumed += 1
        return STATE


def _start(server, login, events, gate=None):
    client = RegistryHttpClient("https://central.example.local", transport=httpx.MockTransport(server.handler))
    lifecycle = NotificationOnboardingLifecycle(
        client, login, gate=gate or BrowserOperationGate(), is_ready=lambda: True, on_event=events.append,
        poll_interval_seconds=0.01, renew_interval_seconds=0.0, tick_seconds=0.01, upload_retry_delay_seconds=0.0,
    )
    worker = JobPollingWorker(lifecycle, SECRET)
    worker.start()
    return worker


def test_full_flow_claim_visible_login_one_upload_and_cleanup(caplog):
    caplog.set_level(logging.DEBUG)
    server, events, material, closed = FakeServer(), [], Material(), []

    async def login(account_id, on_window_opened, timeout_seconds):
        try:
            on_window_opened()
            await asyncio.sleep(0.05)               # the employee types credentials + OTP in SinAuto
            assert account_id == "acct-mamda-nador"
            return material
        finally:
            closed.append(account_id)

    worker = _start(server, login, events)
    try:
        assert server.done.wait(5.0)
    finally:
        assert worker.stop(timeout=3.0)

    paths = [p for p, _, _ in server.requests]
    assert paths[0] == "/runner/notification-onboarding/claim"
    phases = [b["phase"] for p, _, b in server.requests if p.endswith("/renew")]
    assert phases[0] == "OPENING_WINDOW" and set(phases) <= {"OPENING_WINDOW", "WINDOW_OPENED", "WAITING_FOR_LOGIN"}
    assert paths.count(f"/runner/notification-onboarding/{REQUEST_ID}/complete") == 1     # uploaded exactly once
    assert server.completed_bodies == [{"claim_token": TOKEN, "generation": 1, "storage_state": STATE}]
    assert material.consumed == 1 and closed == ["acct-mamda-nador"]
    assert all(auth == f"Bearer {SECRET}" for _, auth, _ in server.requests)              # bearer only
    assert OnboardingEvent.SUCCEEDED in events
    # nothing sensitive reached any log record
    text = " ".join(r.getMessage() for r in caplog.records)
    assert MARKER not in text and TOKEN not in text and SECRET not in text


def test_server_side_cancel_closes_the_window_and_reports_cancelled_over_the_real_client():
    server, events, closed, cancelled = FakeServer("acct-mcma-oujda"), [], [], []
    server.cancel_after_renews = 1

    async def login(account_id, on_window_opened, timeout_seconds):
        try:
            on_window_opened()
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.append(1)
            raise
        finally:
            closed.append(1)

    worker = _start(server, login, events)
    try:
        assert server.done.wait(5.0)
    finally:
        assert worker.stop(timeout=3.0)
    fails = [b for p, _, b in server.requests if p.endswith("/fail")]
    assert [f["reason_code"] for f in fails] == ["CANCELLED"]
    assert not server.completed_bodies and cancelled == [1] and closed == [1]


def test_shutdown_while_login_is_open_closes_it_and_reports_runner_shutdown():
    server, events, closed = FakeServer(), [], []
    opened = threading.Event()

    async def login(account_id, on_window_opened, timeout_seconds):
        try:
            on_window_opened()
            opened.set()
            await asyncio.Event().wait()
        finally:
            closed.append(1)

    worker = _start(server, login, events)
    assert opened.wait(5.0)
    assert worker.stop(timeout=5.0)
    assert closed == [1]
    assert [b["reason_code"] for p, _, b in server.requests if p.endswith("/fail")] == ["RUNNER_SHUTDOWN"]
    assert not server.completed_bodies
    # a stopped worker never resurrects and never opens another window
    worker.start()
    assert not worker.is_alive() and closed == [1]
