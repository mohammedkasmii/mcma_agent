"""INC-17 -- per-account authorization, row-filtering, cross-account
isolation (Oujda/Nador), IDOR attempts."""

from api_test_support import NADOR, OUJDA, create_user, grant_access, login_client


def test_global_permission_without_account_access_is_denied(conn, app_and_client):
    """An operator role globally grants notifications:read, but that
    permission alone unlocks nothing until scoped to an account the user
    was actually granted (correction #9)."""
    app, client, _ = app_and_client
    create_user(conn, "alice", "pw12345", "operator")  # no user_account_access row at all
    login_client(client, "alice", "pw12345")
    response = client.get("/notifications", params={"account_id": OUJDA})
    assert response.status_code == 403


def test_notifications_denied_without_account_access(conn, app_and_client):
    app, client, _ = app_and_client
    user_id = create_user(conn, "alice", "pw12345", "operator")
    login_client(client, "alice", "pw12345")
    # alice has JOBS/NOTIFICATIONS permission via role, but NO account access at all.
    response = client.get("/notifications", params={"account_id": OUJDA})
    assert response.status_code == 403


def test_list_endpoints_return_only_authorized_accounts(conn, app_and_client):
    app, client, _ = app_and_client
    user_id = create_user(conn, "bob", "pw12345", "operator")
    grant_access(conn, user_id, OUJDA)
    conn.execute(
        "INSERT INTO unmatched_notifications (staging_id, account_id, reference, raw_payload, seen_at, resolved) "
        "VALUES ('s1', ?, 'R1', '{}', '2026-01-01T00:00:00+00:00', 0)", (OUJDA,)
    )
    conn.execute(
        "INSERT INTO unmatched_notifications (staging_id, account_id, reference, raw_payload, seen_at, resolved) "
        "VALUES ('s2', ?, 'R2', '{}', '2026-01-01T00:00:00+00:00', 0)", (NADOR,)
    )
    login_client(client, "bob", "pw12345")
    response = client.get("/notifications")  # no explicit account_id -- global list
    assert response.status_code == 200
    accounts_seen = {n["account_id"] for n in response.json()["notifications"]}
    assert accounts_seen == {OUJDA}  # never Nador's row, despite no explicit filter


def test_per_account_enforced_on_each_surface(conn, app_and_client):
    app, client, _ = app_and_client
    user_id = create_user(conn, "carol", "pw12345", "operator")
    grant_access(conn, user_id, OUJDA)
    login_client(client, "carol", "pw12345")

    for path in ("/notifications", "/jobs"):
        denied = client.get(path, params={"account_id": NADOR})
        assert denied.status_code == 403, path
        allowed = client.get(path, params={"account_id": OUJDA})
        assert allowed.status_code == 200, path


def test_oujda_user_cannot_access_nador_and_vice_versa_unless_granted_both(conn, app_and_client):
    app, client, _ = app_and_client
    oujda_user = create_user(conn, "oujda_user", "pw12345", "operator")
    nador_user = create_user(conn, "nador_user", "pw12345", "operator")
    grant_access(conn, oujda_user, OUJDA)
    grant_access(conn, nador_user, NADOR)

    login_client(client, "oujda_user", "pw12345")
    assert client.get("/notifications", params={"account_id": NADOR}).status_code == 403
    assert client.get("/notifications", params={"account_id": OUJDA}).status_code == 200
    client.post("/auth/logout")

    login_client(client, "nador_user", "pw12345")
    assert client.get("/notifications", params={"account_id": OUJDA}).status_code == 403
    assert client.get("/notifications", params={"account_id": NADOR}).status_code == 200

    # Granting BOTH lets one user see both -- proving the denial above was
    # a real authorization check, not a hardcoded account mismatch.
    grant_access(conn, nador_user, OUJDA)
    assert client.get("/notifications", params={"account_id": OUJDA}).status_code == 200


def test_idor_job_id_from_another_account_is_not_listed(conn, app_and_client):
    app, client, _ = app_and_client
    user_id = create_user(conn, "dave", "pw12345", "operator")
    grant_access(conn, user_id, OUJDA)
    conn.execute(
        "INSERT INTO users (user_id, username, password_hash, role, active) VALUES ('u-other','u-other','h','admin',1)"
    )
    conn.execute(
        "INSERT INTO automation_jobs (job_id, account_id, requested_by_user_id, workflow_name, mode, status, "
        "input_hash, idempotency_key, created_at, state_version) VALUES "
        "('job-nador', ?, 'u-other', 'mission_normal', 'DRY_RUN', 'QUEUED', 'h', 'k', '2026-01-01T00:00:00+00:00', 1)",
        (NADOR,),
    )
    login_client(client, "dave", "pw12345")
    response = client.get("/jobs")
    job_ids = {j["job_id"] for j in response.json()["jobs"]}
    assert "job-nador" not in job_ids


def test_notifications_always_carry_account_entity_scope_and_label(conn, app_and_client):
    """Section I (correction batch): combined UI data always retains
    account/entity/scope labels, even in the no-explicit-account_id
    (combined) listing."""
    app, client, _ = app_and_client
    user_id = create_user(conn, "irene", "pw12345", "operator")
    grant_access(conn, user_id, OUJDA)
    conn.execute(
        "INSERT INTO unmatched_notifications (staging_id, account_id, reference, raw_payload, seen_at, resolved) "
        "VALUES ('s1', ?, 'R1', '{}', '2026-01-01T00:00:00+00:00', 0)",
        (OUJDA,),
    )
    login_client(client, "irene", "pw12345")
    response = client.get("/notifications")
    notification = response.json()["notifications"][0]
    assert notification["account_entity"] == "MCMA"
    assert notification["account_scope"] == "OUJDA"
    assert "account_label" in notification
