"""
INC-06 — shared fixtures for the extended offline mock portal (mock_server.py).

The mock is exercised only through FastAPI's TestClient (ASGI transport, no
real socket) — safe under the repo-wide egress lock (`--disable-socket
--allow-hosts=127.0.0.1,::1`). No test in this package may open a real
network connection.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import mock_server

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "contracts"

FINAL_ENDPOINT_ROUTES = {
    "garageModifierValDevis": "/SinAuto_MCMA/expertise/gestiongarage/garageModifierValDevis",
    "validerDevis": "/SinAuto_MCMA/expertise/gestiongarage/validerDevis",
    "deleteDevisDet": "/SinAuto_MCMA/expertise/gestionexpert/deleteDevisDet",
    "expertCloturerMission": "/SinAuto_MCMA/expertise/gestionExpert/expertCloturerMission",
    "cloturerMission": "/SinAuto_MCMA/expertise/gestionExpert/cloturerMission",
    "enregistrerMission": "/SinAuto_MCMA/expertise/gestionExpert/enregistrerMission",
    "expertEnregistrerMission": "/SinAuto_MCMA/expertise/gestionExpert/expertEnregistrerMission",
    "ajouterDocument": "/SinAuto_MCMA/gestion/GED/ajouterDocument",
    "deleteDocument": "/SinAuto_MCMA/gestion/GED/deleteDocument",
    "cloturerTraitement": "/SinAuto_MCMA/expertise/gestionExpert/cloturerTraitement",
}

NORMAL_CHARGE_FIELDS = ("MontantChargeMutuelle", "MontantChargeSocietaire")
PEC_CHARGE_FIELDS = ("DevisMontantChargeMutuelle", "DevisMontantChargeSocietaire")


@pytest.fixture()
def client():
    with TestClient(mock_server.app) as c:
        c.post("/_mock/reset")
        yield c
        c.post("/_mock/reset")


def state(c) -> dict:
    resp = c.get("/_mock/state")
    assert resp.status_code == 200
    return resp.json()
