"""INC-17 correction batch (section G) -- POST /jobs/{id}/review-completed
and POST /jobs/{id}/problem: server-derived actor, per-account
authorization, truthful status transitions, idempotent confirmation,
never accepting account_id/user_id/status from the client body."""

from api_test_support import NADOR, OUJDA, create_user, grant_access, login_client


def _drive_to_ready_for_review(conn, account_id=OUJDA, key="rc-1"):
    from mcma.execution.jobs import (
        enqueue_dry_run,
        enqueue_execute,
        run_dry_run_identity_check,
        run_dry_run_planning,
        run_execute_planning,
        run_execute_write,
    )
    from mcma.execution.inputs import TestOnlyPlaintextEncryptor, compute_content_hash

    encryptor = TestOnlyPlaintextEncryptor()
    payload_bytes = b'{"dossier":"x"}'
    input_hash = compute_content_hash(payload_bytes)

    conn.execute(
        "INSERT OR IGNORE INTO users (user_id, username, password_hash, role, active) "
        "VALUES ('seed-user', 'seed-user', 'h', 'admin', 1)"
    )
    dry_run_id = enqueue_dry_run(
        conn, account_id=account_id, requested_by_user_id="seed-user", workflow_name="mission_normal",
        input_hash=input_hash, typed_input_bytes=payload_bytes, idempotency_key=f"{key}-dry", encryptor=encryptor,
    )

    class _StubProvenance:
        plan_hash = "planhash-rc"

    class _StubPlan:
        needs_review = ()
        provenance = _StubProvenance()

        def canonical_json(self):
            return "{}"

    run_dry_run_planning(conn, dry_run_id, build_plan=lambda: _StubPlan())
    run_dry_run_identity_check(conn, dry_run_id, check_identity_read_only=lambda: True)

    execute_id = enqueue_execute(
        conn, account_id=account_id, requested_by_user_id="seed-user", workflow_name="mission_normal",
        input_hash=input_hash, typed_input_bytes=payload_bytes, idempotency_key=f"{key}-exec", encryptor=encryptor,
        parent_job_id=dry_run_id,
    )
    run_execute_planning(conn, execute_id, rebuild_plan_from_retained_input=lambda: _StubPlan())
    run_execute_write(
        conn, execute_id,
        acquire_lease_and_verify_identity=lambda: object(),
        perform_writes_and_verify=lambda writer: True,
    )
    return execute_id


def test_review_completed_requires_awaiting_confirmation(conn, app_and_client):
    app, client, _ = app_and_client
    user_id = create_user(conn, "alice", "pw12345", "operator")
    grant_access(conn, user_id, OUJDA)
    csrf = login_client(client, "alice", "pw12345")
    job_id = _drive_to_ready_for_review(conn, OUJDA, key="rc-2")

    response = client.post(f"/jobs/{job_id}/review-completed", json={}, headers={"X-CSRF-Token": csrf})
    assert response.status_code == 409
    assert response.json()["error"] == "REVIEW_NOT_AWAITING_CONFIRMATION"


def test_review_completed_succeeds_after_browser_closed(conn, app_and_client):
    from mcma.execution.jobs import transition_on_browser_closed

    app, client, _ = app_and_client
    user_id = create_user(conn, "bob", "pw12345", "operator")
    grant_access(conn, user_id, OUJDA)
    csrf = login_client(client, "bob", "pw12345")
    job_id = _drive_to_ready_for_review(conn, OUJDA, key="rc-3")
    transition_on_browser_closed(conn, job_id)  # -> AWAITING_HUMAN_CONFIRMATION

    response = client.post(f"/jobs/{job_id}/review-completed", json={}, headers={"X-CSRF-Token": csrf})
    assert response.status_code == 200
    assert response.json()["status"] == "HUMAN_CONFIRMED_COMPLETE"


def test_review_completed_is_idempotent(conn, app_and_client):
    from mcma.execution.jobs import transition_on_browser_closed

    app, client, _ = app_and_client
    user_id = create_user(conn, "carol", "pw12345", "operator")
    grant_access(conn, user_id, OUJDA)
    csrf = login_client(client, "carol", "pw12345")
    job_id = _drive_to_ready_for_review(conn, OUJDA, key="rc-4")
    transition_on_browser_closed(conn, job_id)

    first = client.post(f"/jobs/{job_id}/review-completed", json={}, headers={"X-CSRF-Token": csrf})
    second = client.post(f"/jobs/{job_id}/review-completed", json={}, headers={"X-CSRF-Token": csrf})
    assert first.status_code == 200 and second.status_code == 200
    assert first.json()["status"] == second.json()["status"] == "HUMAN_CONFIRMED_COMPLETE"


def test_review_completed_denied_for_a_user_without_account_access(conn, app_and_client):
    from mcma.execution.jobs import transition_on_browser_closed

    app, client, _ = app_and_client
    user_id = create_user(conn, "dave", "pw12345", "operator")
    grant_access(conn, user_id, NADOR)  # NOT the job's account
    csrf = login_client(client, "dave", "pw12345")
    job_id = _drive_to_ready_for_review(conn, OUJDA, key="rc-5")
    transition_on_browser_closed(conn, job_id)

    response = client.post(f"/jobs/{job_id}/review-completed", json={}, headers={"X-CSRF-Token": csrf})
    assert response.status_code == 403


def test_review_completed_ignores_client_supplied_fields(conn, app_and_client):
    from mcma.execution.jobs import transition_on_browser_closed

    app, client, _ = app_and_client
    user_id = create_user(conn, "erin", "pw12345", "operator")
    grant_access(conn, user_id, OUJDA)
    csrf = login_client(client, "erin", "pw12345")
    job_id = _drive_to_ready_for_review(conn, OUJDA, key="rc-6")
    transition_on_browser_closed(conn, job_id)

    response = client.post(
        f"/jobs/{job_id}/review-completed",
        json={"status": "HUMAN_CONFIRMED_COMPLETE", "user_id": "someone-else"},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 400


def test_review_completed_records_the_authenticated_user_as_audit_actor(conn, app_and_client):
    from mcma.execution.jobs import transition_on_browser_closed

    app, client, _ = app_and_client
    user_id = create_user(conn, "frank", "pw12345", "operator")
    grant_access(conn, user_id, OUJDA)
    csrf = login_client(client, "frank", "pw12345")
    job_id = _drive_to_ready_for_review(conn, OUJDA, key="rc-7")
    transition_on_browser_closed(conn, job_id)

    client.post(f"/jobs/{job_id}/review-completed", json={}, headers={"X-CSRF-Token": csrf})
    audit_row = conn.execute(
        "SELECT * FROM audit_events WHERE job_id = ? AND action = 'HUMAN_CONFIRMED_COMPLETE'", (job_id,)
    ).fetchone()
    assert audit_row["actor_user_id"] == user_id


def test_problem_report_moves_job_to_interrupted_never_completed(conn, app_and_client):
    app, client, _ = app_and_client
    user_id = create_user(conn, "grace", "pw12345", "operator")
    grant_access(conn, user_id, OUJDA)
    csrf = login_client(client, "grace", "pw12345")
    job_id = _drive_to_ready_for_review(conn, OUJDA, key="rc-8")

    response = client.post(
        f"/jobs/{job_id}/problem", json={"reason_code": "EMPLOYEE_FOUND_DISCREPANCY"}, headers={"X-CSRF-Token": csrf}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "INTERRUPTED_NEEDS_HUMAN_REVIEW"


def test_problem_report_rejects_an_oversized_reason_code(conn, app_and_client):
    app, client, _ = app_and_client
    user_id = create_user(conn, "iris", "pw12345", "operator")
    grant_access(conn, user_id, OUJDA)
    csrf = login_client(client, "iris", "pw12345")
    job_id = _drive_to_ready_for_review(conn, OUJDA, key="rc-11")

    response = client.post(
        f"/jobs/{job_id}/problem", json={"reason_code": "x" * 201}, headers={"X-CSRF-Token": csrf}
    )
    assert response.status_code == 400


def test_problem_report_rejects_client_supplied_account_id(conn, app_and_client):
    app, client, _ = app_and_client
    user_id = create_user(conn, "henry", "pw12345", "operator")
    grant_access(conn, user_id, OUJDA)
    csrf = login_client(client, "henry", "pw12345")
    job_id = _drive_to_ready_for_review(conn, OUJDA, key="rc-9")

    response = client.post(
        f"/jobs/{job_id}/problem", json={"account_id": NADOR}, headers={"X-CSRF-Token": csrf}
    )
    assert response.status_code == 400


def test_a_write_aborted_workflow_can_never_be_reported_completed_via_the_api(conn, app_and_client):
    """A genuinely failed EXECUTE workflow (WRITE_ABORTED) must never be
    reachable to HUMAN_CONFIRMED_COMPLETE through the API -- confirming it
    fails truthfully (409), never silently reported as HTTP 200 success."""
    from mcma.execution.jobs import transition

    app, client, _ = app_and_client
    user_id = create_user(conn, "irene", "pw12345", "operator")
    grant_access(conn, user_id, OUJDA)
    csrf = login_client(client, "irene", "pw12345")
    job_id = _drive_to_ready_for_review(conn, OUJDA, key="rc-10")
    # Force the failed outcome directly (bypassing run_execute_write's own
    # normal path, which this fixture already drove through once) --
    # WRITE_ABORTED is itself a legitimate terminal outcome under
    # WORKFLOW_STATE_MODEL.md §4.
    transition(conn, job_id, "WRITE_ABORTED", reason_code="TEST_FORCED_ABORT")

    response = client.post(f"/jobs/{job_id}/review-completed", json={}, headers={"X-CSRF-Token": csrf})
    assert response.status_code == 409
    assert response.json()["error"] == "REVIEW_NOT_AWAITING_CONFIRMATION"

    listing = client.get("/jobs", params={"account_id": OUJDA})
    job_row = next(j for j in listing.json()["jobs"] if j["job_id"] == job_id)
    assert job_row["status"] == "WRITE_ABORTED"  # truthfully reported, not coerced to success
