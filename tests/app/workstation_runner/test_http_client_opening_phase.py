"""The OPENING_WINDOW renew phase (lease kept alive while Chromium starts)."""

import httpx

from mcma.app.workstation_runner.protocol import ONBOARDING_PHASES
from mcma.app.workstation_runner.http_client import RegistryHttpClient

SECRET = "mcma_rs_" + "s" * 40
TOKEN = "mcma_ot_" + "t" * 40
REQUEST_ID = "a" * 32


def _client(handler):
    return RegistryHttpClient("https://central.example.local", transport=httpx.MockTransport(handler))


def test_phase_set_is_the_closed_three_value_enum():
    assert ONBOARDING_PHASES == ("OPENING_WINDOW", "WINDOW_OPENED", "WAITING_FOR_LOGIN")


def test_renew_accepts_opening_window_and_sends_it():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen["body"] = json.loads(request.read())
        return httpx.Response(200, json={"lease_expires_at": "t", "server_time": "t", "cancel_requested": False})

    result = _client(handler).renew_notification_onboarding(
        SECRET, request_id=REQUEST_ID, claim_token=TOKEN, generation=1, phase="OPENING_WINDOW",
    )
    assert seen["body"]["phase"] == "OPENING_WINDOW" and result.cancel_requested is False
