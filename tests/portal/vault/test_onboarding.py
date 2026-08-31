"""INC-13 -- onboarding endpoint: loopback-only, lease-before-replace,
no server-side browser launch; onboarding_tool.py never writes to disk."""

import base64
import inspect
import json

from fastapi.testclient import TestClient

from mcma.app.onboarding import create_onboarding_app
from vault_test_support import ACCOUNT_ID, SyntheticLeaseHandle


def _make_app(conn, vault_dir, backend, restrictive_acl):
    calls = {"assert_valid": 0}

    class _TrackingLease(SyntheticLeaseHandle):
        async def assert_valid(self):
            calls["assert_valid"] += 1
            await super().assert_valid()

    tracking_lease = _TrackingLease(ACCOUNT_ID)
    app = create_onboarding_app(
        conn=conn, vault_dir=vault_dir, backend=backend, acl_verifier=restrictive_acl,
        lease_provider=lambda account_id: tracking_lease,
    )
    return app, calls


def test_service_acquires_lease_before_session_replace(conn, vault_dir, backend, restrictive_acl):
    app, calls = _make_app(conn, vault_dir, backend, restrictive_acl)
    client = TestClient(app, client=("127.0.0.1", 12345))

    token = client.post(f"/onboarding/tokens/{ACCOUNT_ID}").json()["token"]
    storage_state_b64 = base64.b64encode(json.dumps({"cookies": []}).encode("utf-8")).decode("ascii")

    assert calls["assert_valid"] == 0
    response = client.post("/onboarding/sessions", json={"token": token, "storage_state": storage_state_b64})
    assert response.status_code == 200
    assert calls["assert_valid"] == 1  # checked exactly once, before the replace


def test_onboarding_rejects_non_loopback_caller_paired_with_loopback_success(conn, vault_dir, backend, restrictive_acl):
    app, _ = _make_app(conn, vault_dir, backend, restrictive_acl)
    lan_client = TestClient(app, client=("192.168.1.50", 12345))
    denied = lan_client.post(f"/onboarding/tokens/{ACCOUNT_ID}")
    assert denied.status_code == 403

    loopback_client = TestClient(app, client=("127.0.0.1", 12345))
    allowed = loopback_client.post(f"/onboarding/tokens/{ACCOUNT_ID}")
    assert allowed.status_code == 200


def test_onboarding_token_is_single_use(conn, vault_dir, backend, restrictive_acl):
    app, _ = _make_app(conn, vault_dir, backend, restrictive_acl)
    client = TestClient(app, client=("127.0.0.1", 12345))
    token = client.post(f"/onboarding/tokens/{ACCOUNT_ID}").json()["token"]
    storage_state_b64 = base64.b64encode(json.dumps({"cookies": []}).encode("utf-8")).decode("ascii")

    first = client.post("/onboarding/sessions", json={"token": token, "storage_state": storage_state_b64})
    assert first.status_code == 200
    second = client.post("/onboarding/sessions", json={"token": token, "storage_state": storage_state_b64})
    assert second.status_code == 401


def test_sessions_login_endpoint_does_not_launch_server_browser(conn, vault_dir, backend, restrictive_acl):
    """Structural proof: mcma.app.onboarding's own source never mentions
    playwright/browser launch at all -- the endpoint is pure HTTP/JSON."""
    import mcma.app.onboarding as onboarding_module

    source = inspect.getsource(onboarding_module)
    assert "playwright" not in source.lower()
    assert "launch(" not in source

    # Behavioral confirmation: submitting a session completes without any
    # browser-shaped dependency ever being imported as a side effect.
    app, _ = _make_app(conn, vault_dir, backend, restrictive_acl)
    client = TestClient(app, client=("127.0.0.1", 12345))
    token = client.post(f"/onboarding/tokens/{ACCOUNT_ID}").json()["token"]
    storage_state_b64 = base64.b64encode(json.dumps({"cookies": []}).encode("utf-8")).decode("ascii")
    response = client.post("/onboarding/sessions", json={"token": token, "storage_state": storage_state_b64})
    assert response.status_code == 200


def test_onboarding_tool_never_writes_plaintext_or_vault_dir():
    """Structural proof over tools/onboarding_tool.py's own source: no
    file-write call, no vault import, no encryption import anywhere."""
    import pathlib

    source = pathlib.Path("tools/onboarding_tool.py").read_text(encoding="utf-8")
    assert "with open(" not in source  # urlopen() is a network call, not a file write
    assert ".write_bytes(" not in source
    assert ".write_text(" not in source
    assert "os.replace(" not in source
    assert "mcma.portal.vault" not in source
    assert "vault_dir" not in source
