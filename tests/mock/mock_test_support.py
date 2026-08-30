"""
INC-06 -- shared constants/helpers for tests/mock/*. Deliberately NOT named
conftest.py: pytest auto-imports every conftest.py it discovers under the
bare module name "conftest", and this repo also has tests/portal/safety/
conftest.py -- two same-named bare modules loaded in one session collide in
sys.modules. A uniquely named support module avoids that entirely.
"""

from pathlib import Path

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


def state(c) -> dict:
    resp = c.get("/_mock/state")
    assert resp.status_code == 200
    return resp.json()
