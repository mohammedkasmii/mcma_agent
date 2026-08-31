"""INC-17 -- typed, non-sensitive error responses with a correlation id.
No raw str(exc)/request body/portal-or-DB detail ever reaches a client;
an unexpected exception still returns a truthful, fixed, generic 500."""

from api_test_support import OUJDA, create_user, login_client


def test_known_error_is_typed_with_a_fixed_status_and_message(app_and_client):
    app, client, _ = app_and_client
    response = client.post("/auth/login", json={"username": "nobody", "password": "wrong"})
    assert response.status_code == 401
    body = response.json()
    assert body["error"] == "INVALID_CREDENTIALS"
    assert "nobody" not in body["message"]  # never echoes client-supplied input


def test_every_error_response_has_a_correlation_id(app_and_client):
    app, client, _ = app_and_client
    response = client.post("/auth/login", json={"username": "nobody", "password": "wrong"})
    body = response.json()
    assert "correlation_id" in body
    assert len(body["correlation_id"]) > 0


def test_unexpected_exception_returns_a_truthful_500_and_redacts_internal_detail(conn, app_and_client):
    from fastapi.testclient import TestClient
    from api_test_support import grant_access

    app, client, _ = app_and_client
    user_id = create_user(conn, "alice", "pw12345", "operator")
    grant_access(conn, user_id, OUJDA)
    csrf = login_client(client, "alice", "pw12345")

    # Malformed JSON body -- request.json() raises inside the route,
    # uncaught by any explicit try/except, reaching the generic Exception
    # handler. raise_server_exceptions=False so THIS test observes the
    # actual HTTP response the handler produces, rather than the test
    # transport re-raising the exception it already turned into one.
    non_raising_client = TestClient(app, client=("127.0.0.1", 12345), raise_server_exceptions=False)
    non_raising_client.cookies = client.cookies
    response = non_raising_client.post(
        "/jobs/dry-runs",
        content=b"{not valid json",
        headers={"X-CSRF-Token": csrf, "Content-Type": "application/json"},
    )
    assert response.status_code == 500
    body = response.json()
    assert body["error"] == "INTERNAL_ERROR"
    assert body["message"] == "an unexpected error occurred"
    assert "not valid json" not in body["message"]
    assert "correlation_id" in body


def test_correlation_ids_are_unique_per_request(app_and_client):
    app, client, _ = app_and_client
    first = client.post("/auth/login", json={"username": "nobody", "password": "wrong"}).json()
    second = client.post("/auth/login", json={"username": "nobody", "password": "wrong"}).json()
    assert first["correlation_id"] != second["correlation_id"]
