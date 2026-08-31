"""Single-office local mode: the employee opens the dashboard and works,
without a bootstrap token or a fifth password.

These tests exist to pin what it is NOT allowed to become. It removes a
login step; it must not remove a boundary. Every one of these failing
means local mode has turned into an authentication bypass.
"""

import pytest
from fastapi.testclient import TestClient

from api_test_support import (
    MAMDA_OUJDA,
    NADOR,
    OUJDA,
    conn,  # noqa: F401
    db_path,  # noqa: F401
)
from mcma.app.api.app import create_api_app
from mcma.app.auth.provider import LocalUserAuthProvider
from mcma.app.auth.sessions import SessionStore
from mcma.app.provisioning import LOCAL_USER_ID, ensure_canonical_accounts, ensure_local_employee
from mcma.execution.inputs import TestOnlyPlaintextEncryptor


def _app(conn, *, local: bool, client_host="127.0.0.1"):
    local_user_id = ensure_local_employee(conn) if local else None
    app = create_api_app(
        conn,
        auth_provider=LocalUserAuthProvider(conn),
        session_store=SessionStore(),
        encryptor=TestOnlyPlaintextEncryptor(),
        secure_cookies=False,
        local_user_id=local_user_id,
    )
    return TestClient(app, client=(client_host, 12345))


def test_the_employee_reaches_the_dashboard_without_signing_in(conn):
    ensure_canonical_accounts(conn)
    client = _app(conn, local=True)
    response = client.get("/accounts")
    assert response.status_code == 200
    assert len(response.json()["accounts"]) == 4


def test_local_mode_is_refused_for_a_non_loopback_client(conn):
    """The check is per REQUEST, not once at startup: a machine reachable
    from the LAN must not hand an authenticated session to whoever
    connects."""
    ensure_canonical_accounts(conn)
    client = _app(conn, local=True, client_host="192.168.1.50")
    assert client.get("/accounts").status_code == 401


def test_without_local_mode_authentication_is_still_required(conn):
    ensure_canonical_accounts(conn)
    client = _app(conn, local=False)
    assert client.get("/accounts").status_code == 401


def test_state_changing_requests_still_require_csrf(conn):
    """No sign-in means nothing issues the CSRF cookie, so the app issues
    it -- but the double-submit check itself is unchanged, and a request
    without the matching header is still refused."""
    ensure_canonical_accounts(conn)
    client = _app(conn, local=True)
    conn.execute(
        "INSERT INTO claims (claim_pk, account_id, portal_claim_id, reference, "
        "first_seen_version, last_seen_version) VALUES (?, ?, '1', 'R', 1, 1)",
        (f"{OUJDA}:1", OUJDA),
    )

    # The cookie is issued...
    client.get("/accounts")
    assert client.cookies.get("mcma_csrf")

    # ...but omitting the header still fails.
    denied = client.post(f"/claims/{OUJDA}:1/action", json={"status": "DONE"})
    assert denied.status_code in (400, 403)

    allowed = client.post(
        f"/claims/{OUJDA}:1/action", json={"status": "DONE"},
        headers={"X-CSRF-Token": client.cookies.get("mcma_csrf")},
    )
    assert allowed.status_code == 200, allowed.text


def test_the_local_user_is_an_operator_not_an_admin(conn):
    """Permission checks must stay meaningful rather than trivially
    satisfied by a role that can do everything."""
    ensure_canonical_accounts(conn)
    ensure_local_employee(conn)
    role = conn.execute("SELECT role FROM users WHERE user_id = ?", (LOCAL_USER_ID,)).fetchone()["role"]
    assert role == "operator"


def test_account_access_is_still_enforced_for_the_local_user(conn):
    """Local mode grants the four provisioned accounts -- not a bypass of
    account filtering. Revoking one hides it again."""
    ensure_canonical_accounts(conn)
    client = _app(conn, local=True)
    conn.execute("DELETE FROM user_account_access WHERE user_id = ? AND account_id = ?",
                 (LOCAL_USER_ID, NADOR))

    visible = {a["account_id"] for a in client.get("/accounts").json()["accounts"]}
    assert NADOR not in visible
    assert OUJDA in visible
    assert client.get(f"/claims?account_id={NADOR}").status_code in (403, 404)


def test_provisioning_the_local_user_is_idempotent(conn):
    ensure_canonical_accounts(conn)
    ensure_local_employee(conn)
    ensure_local_employee(conn)
    users = conn.execute("SELECT count(*) AS n FROM users WHERE user_id = ?", (LOCAL_USER_ID,)).fetchone()
    grants = conn.execute(
        "SELECT count(*) AS n FROM user_account_access WHERE user_id = ?", (LOCAL_USER_ID,)
    ).fetchone()
    assert users["n"] == 1
    assert grants["n"] == 4


def test_local_mode_never_creates_a_portal_account(conn):
    """Adding a person must never invent a portal identity."""
    ensure_canonical_accounts(conn)
    before = conn.execute("SELECT count(*) AS n FROM accounts").fetchone()["n"]
    ensure_local_employee(conn)
    after = conn.execute("SELECT count(*) AS n FROM accounts").fetchone()["n"]
    assert before == after == 4
    assert {MAMDA_OUJDA, OUJDA} <= {
        row["account_id"] for row in conn.execute("SELECT account_id FROM accounts")
    }


def test_startup_refuses_local_mode_on_a_non_loopback_bind(tmp_path):
    """Belt and braces around the per-request check: an install bound to
    the LAN with this enabled must not start at all."""
    from mcma.app.main import startup
    from mcma.core.config import Settings

    settings = Settings(
        db_path=tmp_path / "m.sqlite3",
        vault_dir=tmp_path / "vault",
        dev_mode=True,
        # Explicit test opt-in. These are what select the unsafe backends
        # now; dev_mode alone no longer does.
        allow_test_plaintext_job_inputs=True,
        allow_test_only_session_vault=True,
        local_single_user_mode=True,
        api_host="0.0.0.0",
        mutex_name=f"mcma-test-{tmp_path.name}",
    )
    mutex, api_conn, _, encryptor = startup(settings, _test_only_portable_mutex=True)
    try:
        from mcma.app.main import build_app

        with pytest.raises(ValueError):
            build_app(api_conn, settings, encryptor)
    finally:
        mutex.release()
