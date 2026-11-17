"""The supervised Mode Normal golden canary's ONE switch:
Settings.mode_normal_golden_canary_enabled, read by the central server at
startup from its TOML file or MCMA_MODE_NORMAL_GOLDEN_CANARY_ENABLED.

Off (default): EXECUTE creation stays the fixed 503 -- covered for the
default world by test_central_hardening.py and re-pinned here. On: EXECUTE
creation is admitted ONLY for canary-eligible Mode Normal plans, through
the real central composition (no test-only app wiring)."""

import json

import pytest
from fastapi.testclient import TestClient

import mcma.notifications.service as service_module
from central_test_support import FakeLauncher, central_settings
from mcma.app.auth.passwords import hash_password
from mcma.app.central_server import create_central_server
from mcma.core.central_config import load_central_settings
from mcma.core.config import Settings
from mcma.execution.jobs import transition
from mcma.mapping.wexia import parse_wexia
from mcma.planning.registry import default_registry

OUJDA = "acct-mcma-oujda"
MAMDA_OUJDA = "acct-mamda-oujda"

_NORMAL = {
    "dossier": {"id_sinistre": "699001", "mission_type": "normal", "incident_description": "MODE NORMAL",
                "is_reform": False},
    "vehicule": {"license_plate": "77001-C-3"},
    "chiffrages": [{
        "id": "CH-1", "status": "approved", "is_final": True, "scenario_type": "repair",
        "total_cost": 10, "tax_amount": 2,
        "lignes_pieces": [{"item_type": "part", "item_name": "pare-choc avant", "part_type": "original",
                           "subtotal": 10}],
    }],
}
_PEC = {**_NORMAL, "dossier": {**_NORMAL["dossier"], "mission_type": "garage conventionne",
                                "incident_description": "PEC"}}


@pytest.fixture()
def launcher(monkeypatch):
    fake = FakeLauncher()
    monkeypatch.setattr(service_module, "launch_browser", fake)
    return fake


def _server(tmp_path, **overrides):
    return create_central_server(central_settings(tmp_path, **overrides), _test_only_portable_mutex=True)


def _login(server, client, accounts=(OUJDA,)):
    server.api_conn.execute(
        "INSERT INTO users (user_id, username, password_hash, role, active) "
        "VALUES ('u1', 'agent', ?, 'operator', 1)", (hash_password("pw-for-tests"),),
    )
    for account in accounts:
        server.api_conn.execute(
            "INSERT INTO user_account_access (user_id, account_id, granted_at) VALUES ('u1', ?, 'now')", (account,),
        )
    response = client.post("/auth/login", json={"username": "agent", "password": "pw-for-tests"})
    assert response.status_code == 200
    return {"X-CSRF-Token": response.json()["csrf_token"]}


def _verified_dry_run(server, client, headers, typed_input, *, account=OUJDA, key="dr-1"):
    created = client.post("/jobs/dry-runs", json={"account_id": account, "typed_input": typed_input,
                                                  "idempotency_key": key}, headers=headers)
    assert created.status_code == 200, created.text
    job_id = created.json()["job_id"]
    workflow = created.json()["workflow_name"]
    plan = default_registry().get(workflow)(parse_wexia(json.loads(json.dumps(typed_input))))
    conn = server.api_conn
    transition(conn, job_id, "PLANNING")
    transition(conn, job_id, "PLANNED", plan_hash=plan.provenance.plan_hash)
    transition(conn, job_id, "READ_ONLY_IDENTITY_CHECK")
    transition(conn, job_id, "DRY_RUN_VERIFIED")
    return job_id


# --------------------------------------------------------------------- #
# The setting itself
# --------------------------------------------------------------------- #


def test_the_opt_in_is_disabled_by_default():
    assert Settings().mode_normal_golden_canary_enabled is False


def test_the_opt_in_is_loaded_only_from_server_configuration(tmp_path):
    base = central_settings(tmp_path)
    assert base.mode_normal_golden_canary_enabled is False
    lines = []
    for name in ("api_host", "db_path", "vault_dir", "tls_cert_path", "tls_key_path", "session_vault_key_path",
                 "job_input_key_path", "instance_lock_path", "sinauto_client_pfx_path",
                 "sinauto_client_passphrase_path", "portal_host"):
        value = getattr(base, name)
        lines.append(f"{name} = {json.dumps(str(value))}")
    config = tmp_path / "central.toml"
    config.write_text("\n".join(lines) + "\n", encoding="utf-8")

    assert load_central_settings(config, environ={}).mode_normal_golden_canary_enabled is False
    enabled = load_central_settings(config, environ={"MCMA_MODE_NORMAL_GOLDEN_CANARY_ENABLED": "true"})
    assert enabled.mode_normal_golden_canary_enabled is True
    config.write_text(config.read_text(encoding="utf-8") + "mode_normal_golden_canary_enabled = true\n",
                      encoding="utf-8")
    assert load_central_settings(config, environ={}).mode_normal_golden_canary_enabled is True
    disabled = load_central_settings(config, environ={"MCMA_MODE_NORMAL_GOLDEN_CANARY_ENABLED": "false"})
    assert disabled.mode_normal_golden_canary_enabled is False


# --------------------------------------------------------------------- #
# Through the real central composition
# --------------------------------------------------------------------- #


def test_canary_off_execute_creation_stays_503(tmp_path, launcher):
    server = _server(tmp_path)
    with TestClient(server.app, base_url="https://testserver", client=("127.0.0.1", 5000)) as client:
        headers = _login(server, client)
        parent = _verified_dry_run(server, client, headers, _NORMAL)
        response = client.post(f"/jobs/{parent}/executions", json={}, headers=headers)
        assert response.status_code == 503
        assert response.json()["error"] == "RUNNER_CONTROL_PLANE_UNAVAILABLE"
        count = server.api_conn.execute("SELECT COUNT(*) AS n FROM automation_jobs WHERE mode = 'EXECUTE'").fetchone()
        assert count["n"] == 0


def test_canary_on_admits_an_eligible_mode_normal_execution(tmp_path, launcher):
    server = _server(tmp_path, mode_normal_golden_canary_enabled=True)
    with TestClient(server.app, base_url="https://testserver", client=("127.0.0.1", 5000)) as client:
        headers = _login(server, client)
        parent = _verified_dry_run(server, client, headers, _NORMAL)
        response = client.post(f"/jobs/{parent}/executions", json={}, headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "PLANNED"


def test_canary_on_refuses_pec_before_anything_is_enqueued(tmp_path, launcher):
    server = _server(tmp_path, mode_normal_golden_canary_enabled=True)
    with TestClient(server.app, base_url="https://testserver", client=("127.0.0.1", 5000)) as client:
        headers = _login(server, client)
        parent = _verified_dry_run(server, client, headers, _PEC)
        response = client.post(f"/jobs/{parent}/executions", json={}, headers=headers)
        assert response.status_code == 409
        assert response.json()["error"] == "CANARY_WORKFLOW_NOT_MODE_NORMAL"
        count = server.api_conn.execute("SELECT COUNT(*) AS n FROM automation_jobs WHERE mode = 'EXECUTE'").fetchone()
        assert count["n"] == 0


def test_canary_on_refuses_a_plan_that_needs_review(tmp_path, launcher):
    server = _server(tmp_path, mode_normal_golden_canary_enabled=True)
    needs_review = {**_NORMAL, "dossier": {**_NORMAL["dossier"], "responsibility_rate": 37}}
    with TestClient(server.app, base_url="https://testserver", client=("127.0.0.1", 5000)) as client:
        headers = _login(server, client)
        parent = _verified_dry_run(server, client, headers, needs_review)
        response = client.post(f"/jobs/{parent}/executions", json={}, headers=headers)
        assert response.status_code == 409
        assert response.json()["error"] == "CANARY_PLAN_NEEDS_REVIEW"


def test_canary_on_still_refuses_mamda(tmp_path, launcher):
    server = _server(tmp_path, mode_normal_golden_canary_enabled=True)
    with TestClient(server.app, base_url="https://testserver", client=("127.0.0.1", 5000)) as client:
        headers = _login(server, client, accounts=(OUJDA, MAMDA_OUJDA))
        created = client.post("/jobs/dry-runs", json={"account_id": MAMDA_OUJDA, "typed_input": _NORMAL,
                                                      "idempotency_key": "m1"}, headers=headers)
        # MAMDA work is refused at creation already; an EXECUTE can never follow.
        assert created.status_code in (403, 409)


def test_a_client_cannot_turn_the_canary_on(tmp_path, launcher):
    server = _server(tmp_path)
    with TestClient(server.app, base_url="https://testserver", client=("127.0.0.1", 5000)) as client:
        headers = _login(server, client)
        parent = _verified_dry_run(server, client, headers, _NORMAL)
        for body in ({"mode_normal_golden_canary_enabled": True}, {"execution_profile": "MODE_NORMAL_GOLDEN_CANARY"}):
            response = client.post(f"/jobs/{parent}/executions", json=body, headers=headers)
            assert response.status_code == 503
