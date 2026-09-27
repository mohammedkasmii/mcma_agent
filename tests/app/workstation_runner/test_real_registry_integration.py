"""RELEASE BLOCKER 3 -- integration-style test against the REAL runner
registry/API contract (mcma.app.api.runners + mcma.app.runners.registry),
not a mock that hands back a reduced account list without enforcing server
authorization. RegistryHttpClient talks to the real FastAPI app in-process
via Starlette's own synchronous ASGI test transport (httpx.ASGITransport is
async-only and cannot back a sync httpx.Client, which is what
RegistryHttpClient uses) -- no real sockets, so this respects the egress
lockdown. Everything below `/runner/enroll` and `/runner/heartbeat` is the
genuine server code path: real SQLite-backed eligibility checks, real
ACCOUNT_NOT_ALLOWED enforcement, real digest-based credential lookup."""

import httpx
import pytest
from starlette.testclient import TestClient

from mcma.app.workstation_runner.http_client import RegistryHttpClient
from tests.app.api.api_test_support import (  # noqa: F401 -- csrf_headers used indirectly via helper below
    NADOR, OUJDA, conn, create_user, csrf_headers, db_path, grant_access, login_client,
)

ORIGIN = "https://central.example.local"
PASSWORD = "correct horse battery staple"


@pytest.fixture()
def real_app(conn):
    from mcma.app.api.app import create_api_app
    from mcma.app.auth.provider import LocalUserAuthProvider
    from mcma.app.auth.sessions import SessionStore
    from mcma.execution.inputs import TestOnlyPlaintextEncryptor

    return create_api_app(
        conn, auth_provider=LocalUserAuthProvider(conn), session_store=SessionStore(),
        encryptor=TestOnlyPlaintextEncryptor(), secure_cookies=True, runner_registry=True,
    )


def _asgi_transport(real_app) -> httpx.BaseTransport:
    """A real, synchronous, in-process ASGI transport for the real app --
    Starlette's TestClient builds exactly this internally; reused here so
    RegistryHttpClient (a genuine sync httpx.Client under the hood) can
    drive the real app without a real socket."""
    return TestClient(real_app)._transport


def _admin_client(real_app):
    return httpx.Client(transport=_asgi_transport(real_app), base_url="https://testserver")


def _create_pairing_code(admin_httpx_client, csrf_token: str, target_user_id: str) -> str:
    response = admin_httpx_client.post(
        "/admin/runner-enrollments", json={"target_user_id": target_user_id}, headers=csrf_headers(csrf_token),
    )
    assert response.status_code == 201, response.text
    return response.json()["pairing_code"]


def test_account_removal_reconciliation_against_the_real_registry(conn, real_app):
    """
    1. enroll with Oujda and Nador access;
    2. perform a heartbeat;
    3. remove one account from the employee;
    4. perform the next heartbeat;
    5. verify it succeeds and returns only the remaining account;
    6. verify the runner remains active/online.
    """
    boss_id = create_user(conn, "boss", PASSWORD, "admin")
    emp_id = create_user(conn, "emp", PASSWORD, "operator")
    grant_access(conn, emp_id, OUJDA)
    grant_access(conn, emp_id, NADOR)

    admin_client = _admin_client(real_app)
    # login_client() expects the requests/starlette TestClient's .post(json=...)
    # convention, which httpx.Client also supports identically.
    login_response = admin_client.post("/auth/login", json={"username": "boss", "password": PASSWORD})
    assert login_response.status_code == 200, login_response.text
    csrf_token = login_response.json()["csrf_token"]

    pairing_code = _create_pairing_code(admin_client, csrf_token, emp_id)

    # RegistryHttpClient talks to the SAME real app in-process, over ASGI --
    # this is the actual production client code, not a stand-in.
    runner_client = RegistryHttpClient(ORIGIN, transport=_asgi_transport(real_app))
    try:
        enrolled = runner_client.enroll(pairing_code, workstation_label="Poste-Integration")
        assert set(enrolled.allowed_account_ids) == {OUJDA, NADOR}

        # Step 2: a heartbeat while both accounts are still allowed.
        first_heartbeat = runner_client.heartbeat(enrolled.runner_secret)
        assert first_heartbeat.status == "ACTIVE"
        assert set(first_heartbeat.allowed_account_ids) == {OUJDA, NADOR}

        # Step 3: remove Nador access via the REAL admin API (not raw SQL) --
        # PATCH /admin/users/{id} with a narrower account_ids list.
        patch_response = admin_client.patch(
            f"/admin/users/{emp_id}", json={"account_ids": [OUJDA]}, headers=csrf_headers(csrf_token),
        )
        assert patch_response.status_code == 200, patch_response.text

        # Step 4/5: the NEXT heartbeat must still succeed (sessions=() can
        # never trigger ACCOUNT_NOT_ALLOWED) and report only the remaining
        # account -- this is the real server's own eligibility computation,
        # not a mock handing back a reduced list.
        second_heartbeat = runner_client.heartbeat(enrolled.runner_secret)
        assert second_heartbeat.status == "ACTIVE"
        assert second_heartbeat.allowed_account_ids == (OUJDA,)

        # Step 6: the runner itself remains ACTIVE/ONLINE, not auto-revoked --
        # losing ONE of several accounts is not the fail-closed
        # "loses access to every account" case.
        own_status = admin_client.get(
            "/admin/runners", headers=csrf_headers(csrf_token),
        )
        assert own_status.status_code == 200, own_status.text
        runners = own_status.json()["runners"]
        assert len(runners) == 1
        assert runners[0]["runner_id"] == enrolled.runner_id
        assert runners[0]["status"] in ("ONLINE", "OFFLINE")  # never REVOKED
    finally:
        runner_client.close()
        admin_client.close()


def test_losing_every_account_still_fail_closed_revokes_the_runner(conn, real_app):
    """Sanity check that RELEASE BLOCKER 3's fix does not weaken the
    EXISTING fail-closed rule: losing access to EVERY MCMA account must
    still revoke the runner (registry.py's own enforce_eligibility), even
    though heartbeats now send no sessions at all."""
    boss_id = create_user(conn, "boss", PASSWORD, "admin")
    emp_id = create_user(conn, "emp", PASSWORD, "operator")
    grant_access(conn, emp_id, OUJDA)

    admin_client = _admin_client(real_app)
    login_response = admin_client.post("/auth/login", json={"username": "boss", "password": PASSWORD})
    csrf_token = login_response.json()["csrf_token"]
    pairing_code = _create_pairing_code(admin_client, csrf_token, emp_id)

    runner_client = RegistryHttpClient(ORIGIN, transport=_asgi_transport(real_app))
    try:
        enrolled = runner_client.enroll(pairing_code, workstation_label="Poste-Integration")
        runner_client.heartbeat(enrolled.runner_secret)

        patch_response = admin_client.patch(
            f"/admin/users/{emp_id}", json={"account_ids": []}, headers=csrf_headers(csrf_token),
        )
        assert patch_response.status_code == 200, patch_response.text

        from mcma.app.workstation_runner.http_client import RegistryUnauthorized

        with pytest.raises(RegistryUnauthorized):
            runner_client.heartbeat(enrolled.runner_secret)
    finally:
        runner_client.close()
        admin_client.close()
