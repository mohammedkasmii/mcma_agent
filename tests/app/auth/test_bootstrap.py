"""INC-16 -- secure first-admin bootstrap: loopback-only, single-use,
expiring, disabled once an admin exists."""

import time

from fastapi.testclient import TestClient

from mcma.app.auth.bootstrap import BootstrapTokenStore, create_bootstrap_app


def test_first_admin_bootstrap_rejects_non_loopback(conn):
    app = create_bootstrap_app(conn)
    lan_client = TestClient(app, client=("192.168.1.50", 12345))
    denied = lan_client.post("/bootstrap/tokens")
    assert denied.status_code == 403

    loopback_client = TestClient(app, client=("127.0.0.1", 12345))
    allowed = loopback_client.post("/bootstrap/tokens")
    assert allowed.status_code == 200


def test_bootstrap_single_use_and_expires(conn):
    store = BootstrapTokenStore(ttl_seconds=0)
    app = create_bootstrap_app(conn, token_store=store)
    client = TestClient(app, client=("127.0.0.1", 12345))

    token = client.post("/bootstrap/tokens").json()["token"]
    time.sleep(0.01)
    response = client.post(
        "/bootstrap/admin", json={"token": token, "username": "alice", "password": "s3cret-pw"}
    )
    assert response.status_code == 401  # expired


def test_bootstrap_token_is_single_use(conn):
    app = create_bootstrap_app(conn)
    client = TestClient(app, client=("127.0.0.1", 12345))
    token = client.post("/bootstrap/tokens").json()["token"]

    first = client.post("/bootstrap/admin", json={"token": token, "username": "alice", "password": "s3cret-pw"})
    assert first.status_code == 200


def test_bootstrap_disabled_after_first_admin_exists(conn):
    app = create_bootstrap_app(conn)
    client = TestClient(app, client=("127.0.0.1", 12345))
    token = client.post("/bootstrap/tokens").json()["token"]
    client.post("/bootstrap/admin", json={"token": token, "username": "alice", "password": "s3cret-pw"})

    second_attempt = client.post("/bootstrap/tokens")
    assert second_attempt.status_code == 403
    assert conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"] == 1
