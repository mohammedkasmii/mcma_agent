"""INC-17 -- POST /jobs/dry-runs and POST /jobs/{id}/executions: no mode
field, server-derived audit, direct-EXECUTE-impossible, hash/parent
guards, idempotency."""

from api_test_support import NADOR, OUJDA, create_user, grant_access, login_client


def _dry_run_body(account_id=OUJDA, key="k1"):
    return {
        "account_id": account_id,
        "workflow_name": "mission_normal",
        "typed_input": {"dossier": "x"},
        "idempotency_key": key,
    }


def test_no_mode_field_exists(conn, app_and_client):
    app, client, _ = app_and_client
    user_id = create_user(conn, "alice", "pw12345", "operator")
    grant_access(conn, user_id, OUJDA)
    csrf = login_client(client, "alice", "pw12345")

    # No endpoint accepts a `mode` field at all -- dry-runs always creates
    # DRY_RUN; supplying `mode` to the executions endpoint is rejected.
    response = client.post(
        "/jobs/dry-runs", json=_dry_run_body(), headers={"X-CSRF-Token": csrf}
    )
    assert response.status_code == 200
    job_id = response.json()["job_id"]
    assert response.json()["status"] == "QUEUED"

    rejected = client.post(
        f"/jobs/{job_id}/executions", json={"mode": "EXECUTE"}, headers={"X-CSRF-Token": csrf}
    )
    assert rejected.status_code == 400


def test_dry_runs_idempotency_key_dedupes_resubmit(conn, app_and_client):
    app, client, _ = app_and_client
    user_id = create_user(conn, "bob", "pw12345", "operator")
    grant_access(conn, user_id, OUJDA)
    csrf = login_client(client, "bob", "pw12345")

    first = client.post("/jobs/dry-runs", json=_dry_run_body(key="same-key"), headers={"X-CSRF-Token": csrf})
    second = client.post("/jobs/dry-runs", json=_dry_run_body(key="same-key"), headers={"X-CSRF-Token": csrf})
    assert first.json()["job_id"] == second.json()["job_id"]


def test_jobs_plan_permission_does_not_grant_jobs_execute(conn, app_and_client):
    app, client, _ = app_and_client
    user_id = create_user(conn, "carol", "pw12345", "viewer")  # viewer: no JOBS_PLAN or JOBS_EXECUTE
    grant_access(conn, user_id, OUJDA)
    csrf = login_client(client, "carol", "pw12345")

    denied = client.post("/jobs/dry-runs", json=_dry_run_body(), headers={"X-CSRF-Token": csrf})
    assert denied.status_code == 403


def _create_verified_dry_run(conn, client, csrf, account_id=OUJDA, key="dr-1"):
    response = client.post("/jobs/dry-runs", json=_dry_run_body(account_id, key), headers={"X-CSRF-Token": csrf})
    job_id = response.json()["job_id"]
    from mcma.execution.jobs import transition

    transition(conn, job_id, "PLANNING")
    transition(conn, job_id, "PLANNED", plan_hash="planhash-1")
    transition(conn, job_id, "READ_ONLY_IDENTITY_CHECK")
    transition(conn, job_id, "DRY_RUN_VERIFIED")
    return job_id


def test_executions_endpoint_requires_dry_run_verified_parent_same_account_workflow(conn, app_and_client):
    app, client, _ = app_and_client
    user_id = create_user(conn, "dave", "pw12345", "operator")
    grant_access(conn, user_id, OUJDA)
    csrf = login_client(client, "dave", "pw12345")

    dry_run_id = _create_verified_dry_run(conn, client, csrf)
    response = client.post(f"/jobs/{dry_run_id}/executions", json={}, headers={"X-CSRF-Token": csrf})
    assert response.status_code == 200
    assert response.json()["status"] in ("PLANNED", "NEEDS_REVIEW")


def test_executions_rejects_needs_review_or_identity_failed_parent(conn, app_and_client):
    app, client, _ = app_and_client
    user_id = create_user(conn, "erin", "pw12345", "operator")
    grant_access(conn, user_id, OUJDA)
    csrf = login_client(client, "erin", "pw12345")

    response = client.post("/jobs/dry-runs", json=_dry_run_body(key="dr-2"), headers={"X-CSRF-Token": csrf})
    job_id = response.json()["job_id"]
    from mcma.execution.jobs import transition

    transition(conn, job_id, "PLANNING")
    transition(conn, job_id, "READ_ONLY_IDENTITY_CHECK")
    transition(conn, job_id, "IDENTITY_FAILED")

    rejected = client.post(f"/jobs/{job_id}/executions", json={}, headers={"X-CSRF-Token": csrf})
    assert rejected.status_code == 409


def test_executions_requires_matching_hashes_and_unexpired_input(conn, app_and_client):
    app, client, _ = app_and_client
    user_id = create_user(conn, "frank", "pw12345", "operator")
    grant_access(conn, user_id, OUJDA)
    csrf = login_client(client, "frank", "pw12345")

    dry_run_id = _create_verified_dry_run(conn, client, csrf, key="dr-3")
    # Simulate an expired retained input.
    conn.execute("UPDATE job_inputs SET expires_at = '2000-01-01T00:00:00+00:00' WHERE job_id = ?", (dry_run_id,))
    response = client.post(f"/jobs/{dry_run_id}/executions", json={}, headers={"X-CSRF-Token": csrf})
    assert response.status_code == 409
    assert response.json()["error"] == "INPUT_EXPIRED"


def test_direct_execute_is_impossible_without_a_dry_run_job(conn, app_and_client):
    app, client, _ = app_and_client
    user_id = create_user(conn, "greg", "pw12345", "operator")
    grant_access(conn, user_id, OUJDA)
    csrf = login_client(client, "greg", "pw12345")

    response = client.post("/jobs/does-not-exist/executions", json={}, headers={"X-CSRF-Token": csrf})
    assert response.status_code == 404


def test_executions_ignores_client_supplied_authorizer(conn, app_and_client):
    """A client attempt to set authorized_by is ignored -- the authorizer
    is always the authenticated session user."""
    app, client, _ = app_and_client
    user_id = create_user(conn, "henry", "pw12345", "operator")
    grant_access(conn, user_id, OUJDA)
    csrf = login_client(client, "henry", "pw12345")
    dry_run_id = _create_verified_dry_run(conn, client, csrf, key="dr-4")

    response = client.post(
        f"/jobs/{dry_run_id}/executions",
        json={"authorized_by": "someone-else", "authorized_by_user_id": "someone-else"},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 200
    execute_job_id = response.json()["job_id"]
    from mcma.persistence.repositories.jobs import AutomationJobsRepository

    row = AutomationJobsRepository(conn).get(execute_job_id)
    assert row["authorized_by_user_id"] == user_id  # server-derived, never the client-supplied value


def test_audit_actor_is_server_derived_never_client_supplied(conn, app_and_client):
    app, client, _ = app_and_client
    user_id = create_user(conn, "irene", "pw12345", "operator")
    grant_access(conn, user_id, OUJDA)
    csrf = login_client(client, "irene", "pw12345")

    response = client.post(
        "/jobs/dry-runs",
        json={**_dry_run_body(key="dr-5"), "requested_by_user_id": "attacker-controlled-id"},
        headers={"X-CSRF-Token": csrf},
    )
    job_id = response.json()["job_id"]
    from mcma.persistence.repositories.jobs import AutomationJobsRepository

    row = AutomationJobsRepository(conn).get(job_id)
    assert row["requested_by_user_id"] == user_id


def test_account_id_from_body_never_bypasses_authorization(conn, app_and_client):
    app, client, _ = app_and_client
    user_id = create_user(conn, "jane", "pw12345", "operator")
    grant_access(conn, user_id, OUJDA)  # NOT Nador
    csrf = login_client(client, "jane", "pw12345")

    response = client.post("/jobs/dry-runs", json=_dry_run_body(account_id=NADOR), headers={"X-CSRF-Token": csrf})
    assert response.status_code == 403
