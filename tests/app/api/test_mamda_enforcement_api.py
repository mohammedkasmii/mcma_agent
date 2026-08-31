"""Correction batch (owner amendment) -- MAMDA read-only enforcement,
defense-in-depth layer 1 (the API surface). MAMDA supports notifications
only: POST /jobs/dry-runs and POST /jobs/{id}/executions must reject a
MAMDA account BEFORE enqueueing anything. MCMA is the positive control.
"""

from api_test_support import MAMDA_OUJDA, OUJDA, create_user, grant_access, login_client

# A minimally valid, buildable Wexia payload -- section 3's server-side
# detect_workflow() must succeed for the MCMA positive control to reach
# QUEUED; the MAMDA-rejection tests never reach that step at all (the
# account-type check runs first), so an invalid payload would work there
# too, but using the same valid shape everywhere keeps this file uniform.
VALID_TYPED_INPUT = {
    "dossier": {"reference_number": "REF-1", "mission_type": "normal", "is_reform": False},
    "vehicule": {"license_plate": "11111-A-11"},
    "chiffrages": [
        {
            "status": "approved", "is_final": True, "scenario_type": "repair",
            "total_cost": 10, "tax_amount": 2,
            "lignes_pieces": [{"item_type": "part", "item_name": "x", "part_type": "original", "subtotal": 10}],
        }
    ],
}


def test_dry_run_creation_rejected_for_mamda_account(conn, app_and_client):
    app, client, _ = app_and_client
    user_id = create_user(conn, "alice", "pw12345", "operator")
    grant_access(conn, user_id, MAMDA_OUJDA)
    csrf = login_client(client, "alice", "pw12345")

    response = client.post(
        "/jobs/dry-runs",
        json={
            "account_id": MAMDA_OUJDA,
            "typed_input": VALID_TYPED_INPUT,
            "idempotency_key": "mamda-1",
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 403
    assert response.json()["error"] == "MAMDA_ACCOUNT_NOT_WRITABLE"


def test_no_job_visible_after_mamda_dry_run_rejection(conn, app_and_client):
    app, client, _ = app_and_client
    user_id = create_user(conn, "bob", "pw12345", "operator")
    grant_access(conn, user_id, MAMDA_OUJDA)
    csrf = login_client(client, "bob", "pw12345")

    client.post(
        "/jobs/dry-runs",
        json={
            "account_id": MAMDA_OUJDA,
            "typed_input": VALID_TYPED_INPUT,
            "idempotency_key": "mamda-2",
        },
        headers={"X-CSRF-Token": csrf},
    )
    listing = client.get("/jobs", params={"account_id": MAMDA_OUJDA})
    assert listing.status_code == 200
    assert listing.json()["jobs"] == []


def test_mcma_dry_run_creation_succeeds_as_positive_control(conn, app_and_client):
    app, client, _ = app_and_client
    user_id = create_user(conn, "carol", "pw12345", "operator")
    grant_access(conn, user_id, OUJDA)
    csrf = login_client(client, "carol", "pw12345")

    response = client.post(
        "/jobs/dry-runs",
        json={
            "account_id": OUJDA,
            "typed_input": VALID_TYPED_INPUT,
            "idempotency_key": "mcma-1",
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "QUEUED"
    assert response.json()["workflow_name"] == "mission_normal"


def test_execution_creation_rejected_for_mamda_account(conn, app_and_client):
    """Even a forged/borrowed dry-run job_id for a MAMDA account cannot
    reach the executions endpoint -- account_id is derived from the
    parent job, and the parent could only ever exist for MCMA in the
    first place (dry-run creation itself is rejected above), so this
    proves the executions endpoint's OWN independent check by directly
    seeding a would-be MAMDA parent row underneath the API."""
    app, client, _ = app_and_client
    user_id = create_user(conn, "dave", "pw12345", "operator")
    grant_access(conn, user_id, MAMDA_OUJDA)
    conn.execute(
        "INSERT INTO automation_jobs (job_id, account_id, requested_by_user_id, workflow_name, mode, status, "
        "input_hash, idempotency_key, created_at, state_version) VALUES "
        "('forged-mamda-dry-run', ?, ?, 'mission_normal', 'DRY_RUN', 'DRY_RUN_VERIFIED', 'h', 'k', "
        "'2026-01-01T00:00:00+00:00', 1)",
        (MAMDA_OUJDA, user_id),
    )
    csrf = login_client(client, "dave", "pw12345")

    response = client.post("/jobs/forged-mamda-dry-run/executions", json={}, headers={"X-CSRF-Token": csrf})
    assert response.status_code == 403
    assert response.json()["error"] == "MAMDA_ACCOUNT_NOT_WRITABLE"
