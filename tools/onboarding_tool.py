"""
tools/onboarding_tool.py -- standalone desktop onboarding tool (INC-13).

Runs a REAL headed browser (via mcma.portal.capabilities.LoginCapability)
so a human performs the actual login/OTP themselves; captures the
resulting SessionMaterial IN MEMORY ONLY; hands it to the loopback
onboarding endpoint (mcma.app.onboarding) as a single HTTP POST, then
discards its own reference (SessionMaterial.consume_for_handoff() is
single-use). This tool NEVER writes to disk at all -- no plaintext file,
no vault directory access, no encryption of its own. All persistence
happens service-side, after the service has already acquired the
account's lease.

Not part of the `mcma` import-linter root package (this is a standalone
operator script, run manually by an onboarding technician) -- it may
import playwright/requests directly.
"""

from __future__ import annotations

import base64
import sys


def hand_off_session(base_url: str, token: str, storage_state: dict) -> str:
    """The one network call this tool ever makes to the service. Returns
    the resulting session_id. No file is ever written by this function.
    account_id is never a parameter here -- it travels only inside the
    server-issued, already account-bound token.

    Fable-review correction: base_url is now required to be an explicit
    loopback origin -- previously an operator typo or a malicious
    base_url would exfiltrate the captured session in cleartext to an
    arbitrary host. This is defense-in-depth for an operator-run tool,
    not a substitute for the server's own loopback check."""
    import json
    import urllib.request
    from urllib.parse import urlsplit

    parsed = urlsplit(base_url)
    if parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError(f"refusing to hand off a session to a non-loopback base_url: {base_url!r}")

    payload = json.dumps(
        {"token": token, "storage_state": base64.b64encode(json.dumps(storage_state).encode("utf-8")).decode("ascii")}
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url}/onboarding/sessions", data=payload, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        body = json.loads(response.read().decode("utf-8"))
    return body["session_id"]


async def run_onboarding(base_url: str, account_id: str, token: str) -> str:
    """Launches a real HEADED Chromium, waits for the human to complete
    login, captures SessionMaterial in memory, hands it off, and closes.
    Imports playwright/mcma.portal lazily so importing this module for
    hand_off_session()'s unit tests never requires a browser."""
    from playwright.async_api import async_playwright

    from mcma.portal.capabilities import open_login_session

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        try:
            login = await open_login_session(browser, account_id, contracts=(), allowed_host="")
            material = await login.perform_manual_login()
            storage_state = material.consume_for_handoff()  # single-use; no local copy retained
            session_id = hand_off_session(base_url, token, storage_state)
            return session_id
        finally:
            await browser.close()


if __name__ == "__main__":  # pragma: no cover - manual operator entry point
    import asyncio

    if len(sys.argv) != 4:
        print("usage: onboarding_tool.py <base_url> <account_id> <token>")
        raise SystemExit(2)
    result = asyncio.run(run_onboarding(sys.argv[1], sys.argv[2], sys.argv[3]))
    print(f"session_id={result}")
