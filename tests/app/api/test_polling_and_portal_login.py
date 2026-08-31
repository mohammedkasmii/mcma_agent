"""The two connections that turn built-but-unreachable components into a
working product: notification polling (mcma.notifications.poller) and
dashboard-driven portal login (the /accounts/{id}/login endpoint).

Both are read-or-auth only. Neither can write to a claim, and neither is
affected by the G5 live-write gate.
"""

import asyncio

import pytest

from api_test_support import (
    MAMDA_OUJDA,
    NADOR,
    OUJDA,
    app_and_client,  # noqa: F401
    conn,  # noqa: F401
    create_user,
    csrf_headers,
    db_path,  # noqa: F401
    grant_access,
    login_client,
)
from mcma.notifications.poller import poll_all_accounts, poll_one_account
from mcma.persistence.leases import acquire_lease
from mcma.portal.sinauto_contracts import (
    DEFAULT_SINAUTO_HOST,
    UnreviewedHost,
    auth_contracts,
    notification_contracts,
    sinauto_allowed_host,
)


# --------------------------------------------------------------------- #
# The reviewed real-portal contracts
# --------------------------------------------------------------------- #


def test_only_the_reviewed_portal_or_loopback_is_accepted():
    assert sinauto_allowed_host(DEFAULT_SINAUTO_HOST) == DEFAULT_SINAUTO_HOST
    assert sinauto_allowed_host("127.0.0.1:8080") == "127.0.0.1:8080"
    for bad in ("evil.example.com", "sinauto.mamda-mcma.ma.evil.com", "localhost:8080", ""):
        with pytest.raises(UnreviewedHost):
            sinauto_allowed_host(bad)


def test_there_is_no_write_contract_for_the_real_portal():
    """The live-write gate (G5/INC-23) is what decides whether a row may
    ever be written to the real portal. This module must not quietly
    pre-empt that by shipping a write route."""
    import mcma.portal.sinauto_contracts as module

    assert not hasattr(module, "write_contracts")
    every_contract = auth_contracts() + notification_contracts(DEFAULT_SINAUTO_HOST, ["MISSIONS"])
    assert {c.capability for c in every_contract} <= {"auth", "read"}


def test_a_category_is_reachable_only_if_a_contract_was_installed_for_it():
    contracts = notification_contracts(DEFAULT_SINAUTO_HOST, ["MISSIONS", "RELANCES"])
    routes = {c.route for c in contracts}
    assert any("CodeAlerte/MISSIONS" in r for r in routes)
    assert any("CodeAlerte/RELANCES" in r for r in routes)
    assert not any("CodeAlerte/AUTRE" in r for r in routes)


# --------------------------------------------------------------------- #
# Polling
# --------------------------------------------------------------------- #


class _FakeReader:
    def __init__(self, rows_by_code):
        self._rows = rows_by_code
        self.closed = False

    async def read_notifications(self, code_alerte):
        return tuple(self._rows.get(code_alerte, ()))

    async def close(self):
        self.closed = True


def _poll(conn, account_id, codes, **kwargs):
    defaults = dict(instance_id="test-instance", allowed_host="127.0.0.1:8080",
                    vault_dir=None, crypto_backend=None)
    defaults.update(kwargs)
    return asyncio.run(poll_one_account(conn, object(), account_id, codes, **defaults))


def test_an_account_with_no_session_is_reported_not_crashed(conn):
    """Four accounts are logged in at different times; an account nobody
    has signed into yet is an ordinary state, not an error."""
    assert _poll(conn, OUJDA, ["MISSIONS"]) == "NO_SESSION"


def test_polling_yields_to_a_job_holding_the_account(conn):
    """A form job someone is waiting on must never queue behind a
    notification refresh."""
    held = acquire_lease(conn, OUJDA, "some-other-instance", owner_job_id="job-1", ttl_seconds=300)
    try:
        assert _poll(conn, OUJDA, ["MISSIONS"]) == "LEASE_BUSY"
    finally:
        held.release()


def test_polling_releases_the_lease_it_took(conn):
    _poll(conn, OUJDA, ["MISSIONS"])
    row = conn.execute("SELECT * FROM account_leases WHERE account_id=?", (OUJDA,)).fetchone()
    assert row is None
    # Proven free: another owner can take it immediately.
    acquire_lease(conn, OUJDA, "next", owner_job_id="next-job").release()


def test_one_accounts_failure_never_stops_the_others(conn, monkeypatch):
    seen = []

    async def _one(conn_, browser, account_id, codes, **kwargs):
        seen.append(account_id)
        if account_id == NADOR:
            raise RuntimeError("portal unreachable")
        return "POLLED"

    monkeypatch.setattr("mcma.notifications.poller.poll_one_account", _one)
    outcomes = asyncio.run(poll_all_accounts(
        conn, object(), ["MISSIONS"], instance_id="i", allowed_host="127.0.0.1:8080",
        vault_dir=None, crypto_backend=None,
    ))
    assert outcomes[NADOR] == "ERROR_RuntimeError"
    assert outcomes[OUJDA] == "POLLED"
    # Every account was still attempted.
    assert len(seen) >= 3


def test_mamda_accounts_are_polled_too(conn, monkeypatch):
    """MAMDA cannot be written to, but its notifications are real work."""
    async def _one(conn_, browser, account_id, codes, **kwargs):
        return "POLLED"

    monkeypatch.setattr("mcma.notifications.poller.poll_one_account", _one)
    outcomes = asyncio.run(poll_all_accounts(
        conn, object(), ["MISSIONS"], instance_id="i", allowed_host="127.0.0.1:8080",
        vault_dir=None, crypto_backend=None,
    ))
    assert MAMDA_OUJDA in outcomes


# --------------------------------------------------------------------- #
# The login endpoint
# --------------------------------------------------------------------- #


def _app_with_login(conn, opener):
    from api_test_support import TestClient  # noqa: F401
    from fastapi.testclient import TestClient as Client

    from mcma.app.api.app import create_api_app
    from mcma.app.auth.provider import LocalUserAuthProvider
    from mcma.app.auth.sessions import SessionStore
    from mcma.execution.inputs import TestOnlyPlaintextEncryptor

    app = create_api_app(
        conn,
        auth_provider=LocalUserAuthProvider(conn),
        session_store=SessionStore(),
        encryptor=TestOnlyPlaintextEncryptor(),
        secure_cookies=False,
        portal_login_opener=opener,
    )
    return Client(app, client=("127.0.0.1", 12345))


def test_login_endpoint_is_absent_when_no_browser_is_available(conn, app_and_client):
    """A deployment with no browser must not expose a route that could
    only ever fail."""
    app, client, _ = app_and_client
    user_id = create_user(conn, "alice", "pw12345", "operator")
    grant_access(conn, user_id, OUJDA)
    csrf = login_client(client, "alice", "pw12345")
    response = client.post(f"/accounts/{OUJDA}/login", headers=csrf_headers(csrf))
    assert response.status_code == 404


def test_login_captures_a_session_for_the_requested_account(conn):
    captured = []

    async def _opener(account_id):
        captured.append(account_id)
        return "session-123"

    client = _app_with_login(conn, _opener)
    user_id = create_user(conn, "alice", "pw12345", "operator")
    grant_access(conn, user_id, OUJDA)
    csrf = login_client(client, "alice", "pw12345")

    response = client.post(f"/accounts/{OUJDA}/login", headers=csrf_headers(csrf))
    assert response.status_code == 200, response.text
    assert response.json()["session_id"] == "session-123"
    assert captured == [OUJDA]


def test_cannot_log_in_an_account_you_cannot_access(conn):
    captured = []

    async def _opener(account_id):
        captured.append(account_id)
        return "session-123"

    client = _app_with_login(conn, _opener)
    user_id = create_user(conn, "alice", "pw12345", "operator")
    grant_access(conn, user_id, OUJDA)
    csrf = login_client(client, "alice", "pw12345")

    response = client.post(f"/accounts/{NADOR}/login", headers=csrf_headers(csrf))
    assert response.status_code in (403, 404)
    # The browser was never opened for an account this user cannot reach.
    assert captured == []


def test_a_failed_login_never_leaks_portal_text(conn):
    async def _opener(account_id):
        raise RuntimeError("Mot de passe incorrect pour l'utilisateur ahmed.benali")

    client = _app_with_login(conn, _opener)
    user_id = create_user(conn, "alice", "pw12345", "operator")
    grant_access(conn, user_id, OUJDA)
    csrf = login_client(client, "alice", "pw12345")

    response = client.post(f"/accounts/{OUJDA}/login", headers=csrf_headers(csrf))
    assert response.status_code == 409
    assert "ahmed" not in response.text
    assert "Mot de passe" not in response.text


def test_login_requires_csrf(conn):
    async def _opener(account_id):
        return "session-123"

    client = _app_with_login(conn, _opener)
    user_id = create_user(conn, "alice", "pw12345", "operator")
    grant_access(conn, user_id, OUJDA)
    login_client(client, "alice", "pw12345")

    response = client.post(f"/accounts/{OUJDA}/login")
    assert response.status_code in (400, 403)


# --------------------------------------------------------------------- #
# Session state on /accounts -- what drives the dots on the chips
# --------------------------------------------------------------------- #


def test_accounts_report_whether_a_session_exists(conn, app_and_client):
    app, client, _ = app_and_client
    user_id = create_user(conn, "alice", "pw12345", "operator")
    grant_access(conn, user_id, OUJDA)
    grant_access(conn, user_id, MAMDA_OUJDA)
    login_client(client, "alice", "pw12345")

    accounts = {a["account_id"]: a for a in client.get("/accounts").json()["accounts"]}
    assert accounts[OUJDA]["session_active"] is False

    conn.execute(
        "INSERT INTO portal_sessions (session_id, account_id, storage_ref, status, last_validated_at) "
        "VALUES ('s1', ?, 'ref', 'ACTIVE', '2026-01-01T00:00:00+00:00')", (OUJDA,)
    )
    accounts = {a["account_id"]: a for a in client.get("/accounts").json()["accounts"]}
    assert accounts[OUJDA]["session_active"] is True
    assert accounts[MAMDA_OUJDA]["session_active"] is False


def test_accounts_report_which_are_writable(conn, app_and_client):
    """MCMA can be written to; MAMDA never can. The dashboard shows this
    rather than re-deriving it from the entity string."""
    app, client, _ = app_and_client
    user_id = create_user(conn, "alice", "pw12345", "operator")
    grant_access(conn, user_id, OUJDA)
    grant_access(conn, user_id, MAMDA_OUJDA)
    login_client(client, "alice", "pw12345")

    accounts = {a["account_id"]: a for a in client.get("/accounts").json()["accounts"]}
    assert accounts[OUJDA]["writable"] is True
    assert accounts[MAMDA_OUJDA]["writable"] is False
