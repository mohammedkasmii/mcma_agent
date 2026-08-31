"""Pilot-integration correction (section 2/6) -- GET /accounts: the
dashboard loads the authenticated user's accessible profiles from here,
never a hardcoded account_id in HTML. GET /jobs?job_id= is a single-job
status poll, still fully account-access-filtered."""

from api_test_support import MAMDA_OUJDA, NADOR, OUJDA, create_user, grant_access, login_client


def test_accounts_endpoint_returns_only_the_users_own_accessible_accounts(conn, app_and_client):
    app, client, _ = app_and_client
    user_id = create_user(conn, "alice", "pw12345", "operator")
    grant_access(conn, user_id, OUJDA)
    csrf = login_client(client, "alice", "pw12345")

    response = client.get("/accounts")
    assert response.status_code == 200
    accounts = response.json()["accounts"]
    assert {a["account_id"] for a in accounts} == {OUJDA}
    assert accounts[0]["entity"] == "MCMA"
    assert accounts[0]["scope"] == "OUJDA"


def test_accounts_endpoint_never_returns_an_unauthorized_account(conn, app_and_client):
    app, client, _ = app_and_client
    user_id = create_user(conn, "bob", "pw12345", "operator")
    grant_access(conn, user_id, OUJDA)
    csrf = login_client(client, "bob", "pw12345")

    response = client.get("/accounts")
    account_ids = {a["account_id"] for a in response.json()["accounts"]}
    assert NADOR not in account_ids
    assert MAMDA_OUJDA not in account_ids


def test_accounts_endpoint_returns_multiple_when_granted(conn, app_and_client):
    app, client, _ = app_and_client
    user_id = create_user(conn, "carol", "pw12345", "operator")
    grant_access(conn, user_id, OUJDA)
    grant_access(conn, user_id, NADOR)
    csrf = login_client(client, "carol", "pw12345")

    response = client.get("/accounts")
    assert {a["account_id"] for a in response.json()["accounts"]} == {OUJDA, NADOR}


def test_accounts_endpoint_empty_when_no_access_granted(conn, app_and_client):
    app, client, _ = app_and_client
    create_user(conn, "dave", "pw12345", "operator")
    login_client(client, "dave", "pw12345")

    response = client.get("/accounts")
    assert response.json()["accounts"] == []


def test_jobs_endpoint_filters_by_job_id(conn, app_and_client):
    app, client, _ = app_and_client
    user_id = create_user(conn, "erin", "pw12345", "operator")
    grant_access(conn, user_id, OUJDA)
    conn.execute(
        "INSERT INTO automation_jobs (job_id, account_id, requested_by_user_id, workflow_name, mode, status, "
        "input_hash, idempotency_key, created_at, state_version) VALUES "
        "('job-1', ?, ?, 'mission_normal', 'DRY_RUN', 'QUEUED', 'h', 'k', '2026-01-01T00:00:00+00:00', 1)",
        (OUJDA, user_id),
    )
    conn.execute(
        "INSERT INTO automation_jobs (job_id, account_id, requested_by_user_id, workflow_name, mode, status, "
        "input_hash, idempotency_key, created_at, state_version) VALUES "
        "('job-2', ?, ?, 'mission_normal', 'DRY_RUN', 'QUEUED', 'h', 'k2', '2026-01-01T00:00:00+00:00', 1)",
        (OUJDA, user_id),
    )
    csrf = login_client(client, "erin", "pw12345")

    response = client.get("/jobs", params={"job_id": "job-1"})
    jobs = response.json()["jobs"]
    assert {j["job_id"] for j in jobs} == {"job-1"}


def test_jobs_endpoint_job_id_filter_still_enforces_account_access(conn, app_and_client):
    app, client, _ = app_and_client
    user_id = create_user(conn, "frank", "pw12345", "operator")
    grant_access(conn, user_id, OUJDA)  # NOT Nador
    conn.execute(
        "INSERT INTO users (user_id, username, password_hash, role, active) VALUES ('u-other','u-other','h','admin',1)"
    )
    conn.execute(
        "INSERT INTO automation_jobs (job_id, account_id, requested_by_user_id, workflow_name, mode, status, "
        "input_hash, idempotency_key, created_at, state_version) VALUES "
        "('job-nador', ?, 'u-other', 'mission_normal', 'DRY_RUN', 'QUEUED', 'h', 'k', '2026-01-01T00:00:00+00:00', 1)",
        (NADOR,),
    )
    csrf = login_client(client, "frank", "pw12345")

    response = client.get("/jobs", params={"job_id": "job-nador"})
    assert response.json()["jobs"] == []  # visible by id, but not by account access -- filtered out
