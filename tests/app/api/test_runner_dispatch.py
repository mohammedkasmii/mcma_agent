"""Machine API for workstation job dispatch (Phase 1C-A): POST
/runner/jobs/claim, /runner/jobs/{job_id}/renew, /runner/jobs/{job_id}/release.
Bearer-only, no cookies/CSRF, strict bounded bodies, Cache-Control: no-store,
fixed generic errors, no job/account/employee/mode/workflow choice from the
client -- see mcma.app.runners.dispatch's own module docstring for the
underlying eligibility/atomicity guarantees (covered by
tests/app/runners/test_dispatch.py; this file is the HTTP surface only)."""

import json

import pytest
from fastapi.testclient import TestClient

from api_test_support import (  # noqa: F401
    MAMDA_OUJDA, NADOR, OUJDA, conn, create_user, csrf_headers, db_path, grant_access, login_client,
)
from mcma.app.api.app import create_api_app
from mcma.app.auth.provider import LocalUserAuthProvider
from mcma.app.auth.sessions import SessionStore
from mcma.execution.inputs import TestOnlyPlaintextEncryptor, compute_content_hash
from mcma.persistence.repositories.jobs import AutomationJobsRepository, JobInputsRepository

PASSWORD = "correct horse battery"
ALL = [OUJDA, NADOR, MAMDA_OUJDA]

# A proven-valid minimal Wexia payload (tests/execution/runner/
# runner_test_support.py's own MODE_NORMAL_TYPED_INPUT, duplicated here --
# bounded duplication over a cross-directory import, the established
# INC-06+ convention): parses via parse_wexia, resolves to workflow_name
# "mission_normal", and builds a real, non-needs-review ProposedPlan.
VALID_WORKFLOW_NAME = "mission_normal"
VALID_TYPED_INPUT = {
    "dossier": {
        "id_sinistre": "699001", "mission_type": "normal",
        "incident_description": "MODE NORMAL", "is_reform": False,
    },
    "vehicule": {"license_plate": "77001-C-3"},
    "chiffrages": [{
        "id": "CH-NORMAL-1", "status": "approved", "is_final": True, "scenario_type": "repair",
        "total_cost": 10, "tax_amount": 2,
        "lignes_pieces": [{"item_type": "part", "item_name": "pare-choc avant", "part_type": "original", "subtotal": 10}],
    }],
}


def _app(conn):
    return create_api_app(
        conn, auth_provider=LocalUserAuthProvider(conn), session_store=SessionStore(),
        encryptor=TestOnlyPlaintextEncryptor(), secure_cookies=True, runner_registry=True,
    )


def _client(app):
    return TestClient(app, base_url="https://testserver", client=("203.0.113.9", 4000))


def _user(conn, name, role, accounts=()):
    uid = create_user(conn, name, PASSWORD, role)
    for account in accounts:
        grant_access(conn, uid, account)
    return uid


@pytest.fixture()
def world(conn):
    boss = _user(conn, "boss", "admin", ALL)
    emp = _user(conn, "emp", "operator", [OUJDA])
    app = _app(conn)
    admin = _client(app)
    csrf = login_client(admin, "boss", PASSWORD)
    return {"conn": conn, "app": app, "admin": admin, "csrf": csrf, "boss": boss, "emp": emp}


def _machine(w):
    return _client(w["app"])


def _pair(w, target=None):
    body = {"target_user_id": target or w["emp"]}
    return w["admin"].post("/admin/runner-enrollments", json=body, headers=csrf_headers(w["csrf"]))


def _enroll_runner(w, *, target=None) -> str:
    code = _pair(w, target=target).json()["pairing_code"]
    response = _machine(w).post(
        "/runner/enroll", json={"pairing_code": code, "protocol_version": 1, "app_version": "0.1.0"},
    )
    assert response.status_code == 201, response.text
    return response.json()["runner_secret"]


def _hb(w, secret, *, sessions=None):
    body = {"protocol_version": 1, "app_version": "0.1.0",
            "sessions": sessions if sessions is not None else [{"account_id": OUJDA, "state": "READY"}]}
    return _machine(w).post("/runner/heartbeat", json=body, headers={"Authorization": f"Bearer {secret}"})


def _ready_runner(w, *, target=None) -> str:
    secret = _enroll_runner(w, target=target)
    response = _hb(w, secret)
    assert response.status_code == 200, response.text
    return secret


def _seed_job(
    w, *, job_id, account_id=OUJDA, user_id=None, mode="DRY_RUN", status="QUEUED",
    workflow_name="RENOUVELLEMENT_CONTRAT", typed_input=None,
) -> None:
    conn = w["conn"]
    payload = json.dumps(typed_input if typed_input is not None else {"claim_id": "C-1"}, sort_keys=True).encode("utf-8")
    content_hash = compute_content_hash(payload)
    AutomationJobsRepository(conn).insert(
        job_id=job_id, account_id=account_id, requested_by_user_id=user_id or w["emp"],
        workflow_name=workflow_name, mode=mode, status=status, input_hash=content_hash,
        idempotency_key=job_id, created_at="2026-01-01T00:00:00+00:00", state_version=1,
    )
    JobInputsRepository(conn).insert(
        job_id, content_hash, payload, "CLAIM_DATA", "2026-01-01T00:00:00+00:00", "2027-01-01T00:00:00+00:00",
    )


def _seed_startable_job(w, *, job_id="job-1", user_id=None) -> None:
    _seed_job(
        w, job_id=job_id, user_id=user_id, workflow_name=VALID_WORKFLOW_NAME, typed_input=VALID_TYPED_INPUT,
    )


def _start(w, secret, job_id, claim_token, generation, **overrides):
    body = {"claim_token": claim_token, "generation": generation, **overrides}
    headers = {"Authorization": f"Bearer {secret}"} if secret is not None else {}
    return _machine(w).post(f"/runner/jobs/{job_id}/start", json=body, headers=headers)


def _finish(w, secret, job_id, claim_token, generation, result="IDENTITY_MATCHED", **overrides):
    body = {"claim_token": claim_token, "generation": generation, "result": result, **overrides}
    headers = {"Authorization": f"Bearer {secret}"} if secret is not None else {}
    return _machine(w).post(f"/runner/jobs/{job_id}/finish", json=body, headers=headers)


def _claim(w, secret, **overrides):
    body = {"protocol_version": 1, "app_version": "0.1.0", **overrides}
    headers = {"Authorization": f"Bearer {secret}"} if secret is not None else {}
    return _machine(w).post("/runner/jobs/claim", json=body, headers=headers)


def _renew(w, secret, job_id, claim_token, generation, **overrides):
    body = {"claim_token": claim_token, "generation": generation, **overrides}
    headers = {"Authorization": f"Bearer {secret}"} if secret is not None else {}
    return _machine(w).post(f"/runner/jobs/{job_id}/renew", json=body, headers=headers)


def _release(w, secret, job_id, claim_token, generation, reason_code="RUNNER_SHUTDOWN", **overrides):
    body = {"claim_token": claim_token, "generation": generation, "reason_code": reason_code, **overrides}
    headers = {"Authorization": f"Bearer {secret}"} if secret is not None else {}
    return _machine(w).post(f"/runner/jobs/{job_id}/release", json=body, headers=headers)


# --------------------------------------- claim --------------------------------------- #


def test_claim_returns_the_oldest_eligible_job(world):
    secret = _ready_runner(world)
    _seed_job(world, job_id="job-1")
    response = _claim(world, secret)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert set(body) == {
        "job_id", "mode", "account_id", "workflow_name", "input_hash", "generation",
        "lease_expires_at", "claim_token", "typed_input",
    }
    assert body["job_id"] == "job-1"
    assert body["typed_input"] == {"claim_id": "C-1"}
    assert body["claim_token"].startswith("mcma_ct_")


def test_claim_returns_204_when_there_is_no_eligible_work(world):
    secret = _ready_runner(world)
    response = _claim(world, secret)
    assert response.status_code == 204
    assert response.headers["cache-control"] == "no-store"
    assert response.content == b""


def test_claim_requires_a_bearer_token_not_a_cookie(world):
    secret = _ready_runner(world)
    _seed_job(world, job_id="job-1")
    no_auth = _claim(world, None)
    assert no_auth.status_code == 401

    # An employee session cookie must never authenticate this endpoint.
    admin_client = world["admin"]
    response = admin_client.post("/runner/jobs/claim", json={"protocol_version": 1, "app_version": "0.1.0"})
    assert response.status_code == 401


def test_claim_rejects_a_wrong_bearer_secret(world):
    _seed_job(world, job_id="job-1")
    response = _claim(world, "mcma_rs_not-a-real-secret")
    assert response.status_code == 401


def test_claim_request_cannot_choose_a_job_account_employee_mode_or_workflow(world):
    secret = _ready_runner(world)
    _seed_job(world, job_id="job-1")
    response = _claim(
        world, secret, job_id="job-2", account_id=NADOR, requested_by_user_id=world["boss"],
        mode="EXECUTE", workflow_name="SOMETHING_ELSE",
    )
    assert response.status_code == 400
    assert response.json()["error"] == "BAD_REQUEST"


def test_claim_body_rejects_unknown_and_missing_fields(world):
    secret = _ready_runner(world)
    assert _claim(world, secret, extra_field="x").status_code == 400
    assert _machine(world).post(
        "/runner/jobs/claim", json={"protocol_version": 1}, headers={"Authorization": f"Bearer {secret}"},
    ).status_code == 400


def test_claim_response_never_echoes_the_claim_token_anywhere_but_the_one_field(world):
    secret = _ready_runner(world)
    _seed_job(world, job_id="job-1", typed_input={"secret_field": "SENSITIVE-VALUE"})
    response = _claim(world, secret)
    body = response.json()
    # typed_input legitimately carries verified job data (including this
    # test's own synthetic "sensitive" field) -- but nothing OUTSIDE the
    # dedicated claim_token/typed_input fields may carry it.
    other_fields = {k: v for k, v in body.items() if k not in ("claim_token", "typed_input")}
    assert "SENSITIVE-VALUE" not in json.dumps(other_fields)


def test_a_job_requested_by_a_different_employee_is_not_claimed(world):
    secret = _ready_runner(world)
    other = _user(world["conn"], "other", "operator", [OUJDA])
    _seed_job(world, job_id="job-1", user_id=other)
    assert _claim(world, secret).status_code == 204


def test_mamda_is_never_returned_by_claim_even_if_somehow_queued(world):
    conn = world["conn"]
    grant_access(conn, world["emp"], MAMDA_OUJDA)
    secret = _ready_runner(world)
    _seed_job(world, job_id="job-mamda", account_id=MAMDA_OUJDA)
    assert _claim(world, secret).status_code == 204


# --------------------------------------- renew ---------------------------------------- #


def test_renew_extends_the_lease(world):
    secret = _ready_runner(world)
    _seed_job(world, job_id="job-1")
    claimed = _claim(world, secret).json()
    response = _renew(world, secret, "job-1", claimed["claim_token"], claimed["generation"])
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert set(body) == {"lease_expires_at", "server_time"}
    assert body["lease_expires_at"] > claimed["lease_expires_at"]


def test_renew_requires_bearer_auth(world):
    secret = _ready_runner(world)
    _seed_job(world, job_id="job-1")
    claimed = _claim(world, secret).json()
    response = _renew(world, None, "job-1", claimed["claim_token"], claimed["generation"])
    assert response.status_code == 401


def test_renew_rejects_a_wrong_claim_token_with_a_generic_error(world):
    secret = _ready_runner(world)
    _seed_job(world, job_id="job-1")
    claimed = _claim(world, secret).json()
    response = _renew(world, secret, "job-1", "mcma_ct_not-the-real-token", claimed["generation"])
    assert response.status_code == 404
    body = response.json()
    assert body["error"] == "CLAIM_NOT_FOUND"
    assert "mcma_ct_not-the-real-token" not in json.dumps(body)


def test_renew_rejects_a_stale_generation(world):
    secret = _ready_runner(world)
    _seed_job(world, job_id="job-1")
    claimed = _claim(world, secret).json()
    response = _renew(world, secret, "job-1", claimed["claim_token"], claimed["generation"] + 1)
    assert response.status_code == 404


def test_renew_body_rejects_unknown_and_missing_fields(world):
    secret = _ready_runner(world)
    _seed_job(world, job_id="job-1")
    claimed = _claim(world, secret).json()
    assert _renew(world, secret, "job-1", claimed["claim_token"], claimed["generation"], extra="x").status_code == 400
    response = _machine(world).post(
        f"/runner/jobs/job-1/renew", json={"claim_token": claimed["claim_token"]},
        headers={"Authorization": f"Bearer {secret}"},
    )
    assert response.status_code == 400


def test_a_different_runners_bearer_cannot_renew_this_claim(world):
    secret = _ready_runner(world)
    _seed_job(world, job_id="job-1")
    claimed = _claim(world, secret).json()
    other_emp = _user(world["conn"], "other-emp", "operator", [OUJDA])
    other_secret = _ready_runner(world, target=other_emp)
    response = _renew(world, other_secret, "job-1", claimed["claim_token"], claimed["generation"])
    assert response.status_code == 404


# -------------------------------------- release --------------------------------------- #


def test_release_frees_the_job(world):
    secret = _ready_runner(world)
    _seed_job(world, job_id="job-1")
    claimed = _claim(world, secret).json()
    response = _release(world, secret, "job-1", claimed["claim_token"], claimed["generation"], "RUNNER_SHUTDOWN")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {"status": "RELEASED", "server_time": response.json()["server_time"]}
    again = _claim(world, secret)
    assert again.status_code == 200
    assert again.json()["generation"] == claimed["generation"] + 1


def test_release_rejects_a_client_chosen_free_text_reason(world):
    secret = _ready_runner(world)
    _seed_job(world, job_id="job-1")
    claimed = _claim(world, secret).json()
    response = _release(world, secret, "job-1", claimed["claim_token"], claimed["generation"], "I_QUIT")
    assert response.status_code == 400


def test_release_requires_bearer_auth(world):
    secret = _ready_runner(world)
    _seed_job(world, job_id="job-1")
    claimed = _claim(world, secret).json()
    response = _release(world, None, "job-1", claimed["claim_token"], claimed["generation"])
    assert response.status_code == 401


def test_release_body_rejects_unknown_and_missing_fields(world):
    secret = _ready_runner(world)
    _seed_job(world, job_id="job-1")
    claimed = _claim(world, secret).json()
    assert _release(
        world, secret, "job-1", claimed["claim_token"], claimed["generation"], "RUNNER_SHUTDOWN", extra="x",
    ).status_code == 400


# ---------------------------------------- start ---------------------------------------- #


def test_start_moves_to_running_and_returns_a_plan_hash(world):
    secret = _ready_runner(world)
    _seed_startable_job(world)
    claimed = _claim(world, secret).json()
    response = _start(world, secret, "job-1", claimed["claim_token"], claimed["generation"])
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["status"] == "RUNNING"
    assert body["job_status"] == "READ_ONLY_IDENTITY_CHECK"
    assert body["plan_hash"]
    job = world["conn"].execute("SELECT status FROM automation_jobs WHERE job_id = 'job-1'").fetchone()
    assert job["status"] == "READ_ONLY_IDENTITY_CHECK"


def test_start_lands_needs_review_without_a_plan_hash(world):
    secret = _ready_runner(world)
    needs_review_input = {**VALID_TYPED_INPUT, "dossier": {**VALID_TYPED_INPUT["dossier"], "responsibility_rate": 37}}
    _seed_job(world, job_id="job-1", workflow_name=VALID_WORKFLOW_NAME, typed_input=needs_review_input)
    claimed = _claim(world, secret).json()
    response = _start(world, secret, "job-1", claimed["claim_token"], claimed["generation"])
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "NEEDS_REVIEW"
    assert "plan_hash" not in body
    job = world["conn"].execute("SELECT status FROM automation_jobs WHERE job_id = 'job-1'").fetchone()
    assert job["status"] == "NEEDS_REVIEW"


def test_start_requires_bearer_auth(world):
    secret = _ready_runner(world)
    _seed_startable_job(world)
    claimed = _claim(world, secret).json()
    response = _start(world, None, "job-1", claimed["claim_token"], claimed["generation"])
    assert response.status_code == 401


def test_start_body_rejects_unknown_and_missing_fields(world):
    secret = _ready_runner(world)
    _seed_startable_job(world)
    claimed = _claim(world, secret).json()
    assert _start(world, secret, "job-1", claimed["claim_token"], claimed["generation"], extra="x").status_code == 400
    response = _machine(world).post(
        "/runner/jobs/job-1/start", json={"claim_token": claimed["claim_token"]},
        headers={"Authorization": f"Bearer {secret}"},
    )
    assert response.status_code == 400


def test_start_cannot_choose_a_job_account_or_mode(world):
    """The start body carries only claim_token/generation -- a caller
    cannot add a job/account/mode field to influence which job starts."""
    secret = _ready_runner(world)
    _seed_startable_job(world)
    claimed = _claim(world, secret).json()
    response = _start(
        world, secret, "job-1", claimed["claim_token"], claimed["generation"],
        account_id=NADOR, mode="EXECUTE",
    )
    assert response.status_code == 400


def test_start_rejects_a_wrong_claim_token(world):
    secret = _ready_runner(world)
    _seed_startable_job(world)
    claimed = _claim(world, secret).json()
    response = _start(world, secret, "job-1", "mcma_ct_not-the-real-token", claimed["generation"])
    assert response.status_code == 404
    assert response.json()["error"] == "CLAIM_NOT_FOUND"


def test_a_second_start_on_the_same_claim_is_refused(world):
    secret = _ready_runner(world)
    _seed_startable_job(world)
    claimed = _claim(world, secret).json()
    first = _start(world, secret, "job-1", claimed["claim_token"], claimed["generation"])
    assert first.status_code == 200
    second = _start(world, secret, "job-1", claimed["claim_token"], claimed["generation"])
    assert second.status_code == 404


# --------------------------------------- finish ---------------------------------------- #


def test_finish_identity_matched_lands_dry_run_verified(world):
    secret = _ready_runner(world)
    _seed_startable_job(world)
    claimed = _claim(world, secret).json()
    _start(world, secret, "job-1", claimed["claim_token"], claimed["generation"])
    response = _finish(world, secret, "job-1", claimed["claim_token"], claimed["generation"], "IDENTITY_MATCHED")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["status"] == "SUCCEEDED"
    assert body["job_status"] == "DRY_RUN_VERIFIED"
    job = world["conn"].execute("SELECT status FROM automation_jobs WHERE job_id = 'job-1'").fetchone()
    assert job["status"] == "DRY_RUN_VERIFIED"


@pytest.mark.parametrize("result", ["IDENTITY_NOT_MATCHED", "SESSION_UNAVAILABLE", "PORTAL_READ_FAILED", "RUNNER_CANCELLED"])
def test_finish_non_match_results_land_identity_failed(world, result):
    secret = _ready_runner(world)
    _seed_startable_job(world)
    claimed = _claim(world, secret).json()
    _start(world, secret, "job-1", claimed["claim_token"], claimed["generation"])
    response = _finish(world, secret, "job-1", claimed["claim_token"], claimed["generation"], result)
    assert response.status_code == 200
    assert response.json()["job_status"] == "IDENTITY_FAILED"


def test_finish_rejects_an_arbitrary_result(world):
    secret = _ready_runner(world)
    _seed_startable_job(world)
    claimed = _claim(world, secret).json()
    _start(world, secret, "job-1", claimed["claim_token"], claimed["generation"])
    response = _finish(world, secret, "job-1", claimed["claim_token"], claimed["generation"], "MADE_UP_RESULT")
    assert response.status_code == 400


def test_finish_requires_bearer_auth(world):
    secret = _ready_runner(world)
    _seed_startable_job(world)
    claimed = _claim(world, secret).json()
    _start(world, secret, "job-1", claimed["claim_token"], claimed["generation"])
    response = _finish(world, None, "job-1", claimed["claim_token"], claimed["generation"])
    assert response.status_code == 401


def test_finish_body_rejects_unknown_and_missing_fields(world):
    secret = _ready_runner(world)
    _seed_startable_job(world)
    claimed = _claim(world, secret).json()
    _start(world, secret, "job-1", claimed["claim_token"], claimed["generation"])
    assert _finish(
        world, secret, "job-1", claimed["claim_token"], claimed["generation"], "IDENTITY_MATCHED", extra="x",
    ).status_code == 400
    response = _machine(world).post(
        "/runner/jobs/job-1/finish", json={"claim_token": claimed["claim_token"], "generation": claimed["generation"]},
        headers={"Authorization": f"Bearer {secret}"},
    )
    assert response.status_code == 400


def test_finish_before_start_is_refused(world):
    secret = _ready_runner(world)
    _seed_startable_job(world)
    claimed = _claim(world, secret).json()
    response = _finish(world, secret, "job-1", claimed["claim_token"], claimed["generation"], "IDENTITY_MATCHED")
    assert response.status_code == 404


def test_duplicate_identical_finish_is_idempotent(world):
    secret = _ready_runner(world)
    _seed_startable_job(world)
    claimed = _claim(world, secret).json()
    _start(world, secret, "job-1", claimed["claim_token"], claimed["generation"])
    first = _finish(world, secret, "job-1", claimed["claim_token"], claimed["generation"], "IDENTITY_MATCHED")
    second = _finish(world, secret, "job-1", claimed["claim_token"], claimed["generation"], "IDENTITY_MATCHED")
    assert first.status_code == 200 and second.status_code == 200
    # server_time legitimately reflects each real call's own wall-clock
    # moment (unlike the dispatch-layer unit test, the API layer injects no
    # fixed `now`) -- everything else must be identical.
    assert first.json()["status"] == second.json()["status"] == "SUCCEEDED"
    assert first.json()["job_status"] == second.json()["job_status"] == "DRY_RUN_VERIFIED"


def test_conflicting_finish_is_refused(world):
    secret = _ready_runner(world)
    _seed_startable_job(world)
    claimed = _claim(world, secret).json()
    _start(world, secret, "job-1", claimed["claim_token"], claimed["generation"])
    _finish(world, secret, "job-1", claimed["claim_token"], claimed["generation"], "IDENTITY_MATCHED")
    conflicting = _finish(world, secret, "job-1", claimed["claim_token"], claimed["generation"], "IDENTITY_NOT_MATCHED")
    assert conflicting.status_code == 404
