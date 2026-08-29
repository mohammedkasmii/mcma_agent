"""
tests/test_features.py — Feature Flag & Safety Interceptor Guards
=================================================================
Verifies that the Phase 2 form filling agent is disabled by default, that every
entry point refuses cleanly, and that the safety interceptor blocks the endpoints
that actually exist on the portal.
"""

import asyncio
import importlib

import pytest
from fastapi.testclient import TestClient

import core.features as features
import main
import workflows.fill_dossier as fill_dossier
from browser.safety_interceptor import MUTATING_ENDPOINTS, BLOCKED_SENTINEL_KEY


client = TestClient(main.app)


# ---------------------------------------------------------------------------
# Default state
# ---------------------------------------------------------------------------

def test_form_filling_disabled_by_default():
    """The agent must be OFF unless explicitly unlocked via the environment."""
    assert features.FORM_FILLING_ENABLED is False


def test_env_flag_parsing(monkeypatch):
    """Unlocking is possible from the environment, without editing source."""
    for truthy in ("1", "true", "TRUE", "yes", "on", "oui"):
        monkeypatch.setenv("MCMA_ENABLE_FORM_FILLING", truthy)
        assert features._env_flag("MCMA_ENABLE_FORM_FILLING") is True
    for falsy in ("0", "false", "no", "", "off"):
        monkeypatch.setenv("MCMA_ENABLE_FORM_FILLING", falsy)
        assert features._env_flag("MCMA_ENABLE_FORM_FILLING") is False


def test_require_form_filling_raises_when_disabled():
    with pytest.raises(features.FeatureDisabledError):
        features.require_form_filling()


# ---------------------------------------------------------------------------
# HTTP entry points
# ---------------------------------------------------------------------------

def test_fill_dossier_returns_503():
    resp = client.post("/api/v1/fill-dossier", json={"payload": {}})
    assert resp.status_code == 503
    assert "désactivé" in resp.json()["detail"]


def test_fill_dossier_from_wexia_returns_503():
    resp = client.post("/api/v1/fill-dossier-from-wexia", json={"wexia_payload": {}})
    assert resp.status_code == 503


def test_health_reports_feature_state():
    body = client.get("/health").json()
    assert body["features"]["form_filling"] is False


def test_features_endpoint():
    body = client.get("/api/v1/features").json()
    assert body["features"]["form_filling"] is False


def test_operations_hub_unaffected_by_the_flag():
    """Disabling form filling must not affect the notification hub."""
    assert client.get("/api/v1/state").status_code == 200
    assert client.get("/api/v1/accounts").status_code == 200


def test_legacy_json_endpoints_are_gone():
    """
    These wrote to logs/*.json — a second store that silently diverged from
    SQLite after the migration. /notification-actions in particular did an
    unguarded read-modify-write, the exact race Phase 1 removed. They must not
    come back: a stale browser tab hitting one would lose an employee's work.
    """
    # POSTs come back 405 rather than 404 because StaticFiles is mounted at "/"
    # and answers unmatched paths. Either way the route is gone and no write
    # can land.
    gone = {404, 405}
    for path in ("/api/v1/notification-actions", "/api/v1/cached-notifications",
                 "/api/v1/notifications"):
        assert client.get(path).status_code in gone, f"{path} is still reachable"
    assert client.post("/api/v1/auth/launch-login").status_code in gone
    assert client.post("/api/v1/notification-actions",
                       json={"reference": "R-1", "status": "DONE"}).status_code in gone


# ---------------------------------------------------------------------------
# Innermost guard
# ---------------------------------------------------------------------------

def test_process_workflow_refuses_before_touching_a_browser():
    """
    process_workflow is the single choke point every caller passes through,
    including run_dossier.py which imports it directly. It now lives in
    workflows/, not in the API layer.
    """
    with pytest.raises(features.FeatureDisabledError):
        asyncio.run(fill_dossier.process_workflow({"matricule": "12345-A-7"}))


# ---------------------------------------------------------------------------
# Safety interceptor — §11.0 regression guards
# ---------------------------------------------------------------------------

def test_real_row_write_endpoints_are_blocked():
    """
    Regression guard for the §11.0 gap: these endpoints exist on the portal and
    must be intercepted. createRapportDefDet was previously missing entirely.
    """
    for endpoint in ("createRapportDefDet", "updateDevisDet", "deleteDevisDet"):
        assert any(endpoint in p for p in MUTATING_ENDPOINTS), f"{endpoint} not blocked"


def test_final_validation_endpoints_are_blocked():
    for endpoint in (
        "garageModifierValDevis",
        "validerDevis",
        "expertEnregistrerMission",
        "cloturerMission",
        "cloturerTraitement",
    ):
        assert any(endpoint in p for p in MUTATING_ENDPOINTS), f"{endpoint} not blocked"


def test_phantom_endpoint_removed():
    """
    createDevisDet does not exist on the portal. Keeping it in the list creates
    false confidence that row creation is guarded when it is not.
    """
    assert not any("createDevisDet" in p for p in MUTATING_ENDPOINTS)


def test_blocked_sentinel_is_defined():
    """Blocked writes must be identifiable so callers can fail closed (§11.3)."""
    assert BLOCKED_SENTINEL_KEY == "__mcma_blocked"
