"""
mock_server.py -- Local offline MCMA simulation server (INC-06)
================================================================
An offline, fully self-contained replica of the SinAuto/MCMA portal DOM,
row-op endpoints, native-calculation contracts, and notification/auth
surface, used only as test infrastructure (docs/architecture/MODULE_BOUNDARIES.md
tags this file "test infrastructure, loopback-only, not production").

Everything under the /_mock/ prefix is a test-harness-only convenience
invented for this repository's own offline tests. It is never a real portal
path, is never eligible for any live allowlist, and grants no writer
capability of any kind -- see tests/fixtures/contracts/*.json for the
explicit evidence classification of every contract this file exposes.

Fully offline: no external CDN, font, or stylesheet reference of any kind.
This file renders and runs the same way with no network access, because it
will later be exercised by a loopback-only headless Chromium (INC-07+).

Run locally:
    python mock_server.py
Access via:
    http://127.0.0.1:8080/SinAuto_MCMA/expertise/gestionexpert/index
"""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from urllib.parse import parse_qsl

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

app = FastAPI(title="MCMA Local Mock Test Server")


async def _read_form(request: Request) -> dict:
    """Dependency-free application/x-www-form-urlencoded parser (avoids an
    added python-multipart dependency; no file uploads are ever needed by
    this mock's own row/final endpoints)."""
    body = await request.body()
    return dict(parse_qsl(body.decode("utf-8")))

# ---------------------------------------------------------------------------
# Charge-field protection (never directly writable through any endpoint)
# ---------------------------------------------------------------------------

NORMAL_CHARGE_FIELDS = ("MontantChargeMutuelle", "MontantChargeSocietaire")
PEC_CHARGE_FIELDS = ("DevisMontantChargeMutuelle", "DevisMontantChargeSocietaire")
ALL_CHARGE_FIELDS = set(NORMAL_CHARGE_FIELDS) | set(PEC_CHARGE_FIELDS)


def _reject_if_charge_fields_present(payload: dict, workflow: str):
    """Fail-closed guard: reject the whole request (not merely drop the
    field) if a caller attempts to directly submit a charge-mutuelle /
    charge-societaire value on any endpoint. The only way either field is
    ever set is through the workflow's native-calculation simulation."""
    hit = ALL_CHARGE_FIELDS.intersection(payload.keys())
    if hit:
        MOCK_STATE["observability"]["direct_charge_write_attempts"][workflow] += 1
        return JSONResponse(
            {
                "state": "error",
                "reason": "DIRECT_CHARGE_FIELD_WRITE_REJECTED",
                "fields": sorted(hit),
            }
        )
    return None


# ---------------------------------------------------------------------------
# Final / dossier-level endpoints -- meaningful sentinels, never real writes
# ---------------------------------------------------------------------------

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
# NOTE: `createDevisDet` is intentionally NOT registered here. It is a
# phantom in the legacy interceptor block list with no real portal
# counterpart (docs/recovery/PORTAL_CONTRACT.md §8) -- adding it to the mock
# would misrepresent the contract.


def _make_final_endpoint_handler(name: str):
    async def handler(request: Request):
        try:
            form = await _read_form(request)
        except Exception:
            form = {}
        MOCK_STATE["observability"]["final_endpoint_hits"][name] += 1
        print(f"[MOCK API] final-endpoint sentinel hit: {name} payload={form}")
        # Deliberate failure -- never a fake 200 "success", never a state
        # mutation, never a finalized dossier.
        return JSONResponse(
            {"state": "error", "reason": "FINAL_ACTION_PERMANENTLY_PROHIBITED", "endpoint": name}
        )

    return handler


for _name, _route in FINAL_ENDPOINT_ROUTES.items():
    app.add_api_route(_route, _make_final_endpoint_handler(_name), methods=["POST"])


# ---------------------------------------------------------------------------
# Mock state (deterministic; fully restored by /_mock/reset)
# ---------------------------------------------------------------------------


def _initial_state() -> dict:
    return {
        "last_saved_mission": None,
        "validated_devis_payload": None,
        "uploaded_documents": [],
        # INC-08 synthetic-only marker: flips true once /front/Login/login
        # succeeds, so /login can reflect logged-in markers for the
        # isolated-CI LoginCapability proof test. Never a real auth state.
        "logged_in": False,
        "rows": {
            "normal": [],
            # Immutable baseline evidence: the garage's original quote.
            "pec_original": [
                {"IdDevisDet": 1, "IdRubrique": "3", "LibRubrique": "TOTAL PIECES OCCASIONS / RECUPERABLES", "MontantHT": "4750.00", "Taxe": "950.00", "MontantTTC": "5700.00"},
                {"IdDevisDet": 2, "IdRubrique": "7", "LibRubrique": "MAIN D'OEUVRE CARROSSERIE", "MontantHT": "1820.00", "Taxe": "364.00", "MontantTTC": "2184.00"},
                {"IdDevisDet": 3, "IdRubrique": "12", "LibRubrique": "MAIN D'OEUVRE PEINTURE", "MontantHT": "1680.00", "Taxe": "336.00", "MontantTTC": "2016.00"},
                {"IdDevisDet": 4, "IdRubrique": "16", "LibRubrique": "PEINTURES ET INGREDIENTS", "MontantHT": "1083.33", "Taxe": "216.67", "MontantTTC": "1300.00"},
            ],
            # Separate, independently mutable "validated" table.
            "pec_validated": [
                {"IdDevisDet": 1, "IdRubrique": "3", "LibRubrique": "TOTAL PIECES OCCASIONS / RECUPERABLES", "MontantHT": "4750.00", "Taxe": "950.00", "MontantTTC": "5700.00", "TauxVetuste": "0.00", "MontantVetuste": "0.00"},
                {"IdDevisDet": 2, "IdRubrique": "7", "LibRubrique": "MAIN D'OEUVRE CARROSSERIE", "MontantHT": "1820.00", "Taxe": "364.00", "MontantTTC": "2184.00", "TauxVetuste": "0.00", "MontantVetuste": "0.00"},
                {"IdDevisDet": 3, "IdRubrique": "12", "LibRubrique": "MAIN D'OEUVRE PEINTURE", "MontantHT": "1680.00", "Taxe": "336.00", "MontantTTC": "2016.00", "TauxVetuste": "0.00", "MontantVetuste": "0.00"},
                {"IdDevisDet": 4, "IdRubrique": "16", "LibRubrique": "PEINTURES ET INGREDIENTS", "MontantHT": "1083.33", "Taxe": "216.67", "MontantTTC": "1300.00", "TauxVetuste": "0.00", "MontantVetuste": "0.00"},
            ],
        },
        "submitted_normal_temp_ids": [],
        "submitted_pec_nonces": [],
        "next_normal_row_id": 1,
        "financial_summary": {"MODE_NORMAL": None, "GARAGE_CONVENTIONNE": None},
        "mismatch_injected": {"MODE_NORMAL": False, "GARAGE_CONVENTIONNE": False},
        "observability": {
            "row_endpoint_calls": {
                "MODE_NORMAL": {"createRapportDefDet": 0},
                "GARAGE_CONVENTIONNE": {"updateDevisDet": 0},
            },
            "duplicate_checkmark_attempts": {"MODE_NORMAL": 0, "GARAGE_CONVENTIONNE": 0},
            "field_event_history": {"MODE_NORMAL": [], "GARAGE_CONVENTIONNE": []},
            "redraw_version": {"MODE_NORMAL": 0, "GARAGE_CONVENTIONNE": 0},
            "native_calculation_calls": {"MODE_NORMAL": 0, "GARAGE_CONVENTIONNE": 0},
            "calculation_version": {"MODE_NORMAL": 0, "GARAGE_CONVENTIONNE": 0},
            "direct_charge_write_attempts": {"MODE_NORMAL": 0, "GARAGE_CONVENTIONNE": 0},
            "final_endpoint_hits": {name: 0 for name in FINAL_ENDPOINT_ROUTES},
            "preflight_calls": {"GARAGE_CONVENTIONNE": []},
        },
    }


MOCK_STATE = _initial_state()


# ---------------------------------------------------------------------------
# Native-calculation simulation (shared by the two mock-only mirror routes)
# ---------------------------------------------------------------------------


def _to_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


_CENT = Decimal("0.01")


def _to_decimal(value, default: str = "0.00") -> Decimal:
    """Exact Decimal/HALF_UP parsing -- never float/parseFloat-equivalent
    arithmetic for a monetary value (mirrors mcma.core.money.Money's own
    convention). An unparseable/absent value defaults rather than raising:
    the mock's calculation inputs are always caller-supplied strings from
    an editable summary field, and a blank field means "zero", not a
    request failure."""
    try:
        return Decimal(str(value)).quantize(_CENT, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(default)


# INC-09B amendment #2: the nine PORTAL_ROW_WORKFLOWS.md 3.2 fields. The
# first two are CONFIRMED_RECOVERED_PEC_DOM_EVIDENCE (#DevisMontant
# ChargeMutuelle/#DevisMontantChargeSocietaire); the remaining seven are
# MOCK_ONLY/UNCONFIRMED -- see
# tests/fixtures/contracts/pec_financial_summary_mock_only.json. This
# mock's own arithmetic relating them is ALSO MOCK_ONLY/UNCONFIRMED: it is
# a plausible test fixture, never claimed as the real portal's formula.
def _compute_pec_financial_summary(payload: dict) -> dict:
    total_ttc = _to_decimal(payload.get("total_ttc"))
    franchise = _to_decimal(payload.get("franchise"))
    vetuste = _to_decimal(payload.get("vetuste"))
    remise = _to_decimal(payload.get("remise"))
    part_resp = _to_decimal(payload.get("part_resp"), "100.00")
    total_tva = _to_decimal(payload.get("total_tva"))

    charge_societaire = ((franchise * part_resp / Decimal("100")) + vetuste).quantize(
        _CENT, rounding=ROUND_HALF_UP
    )
    charge_mutuelle_raw = total_ttc - charge_societaire - remise
    charge_mutuelle = (charge_mutuelle_raw if charge_mutuelle_raw > 0 else Decimal("0.00")).quantize(
        _CENT, rounding=ROUND_HALF_UP
    )
    base_indemnite = (total_ttc - vetuste).quantize(_CENT, rounding=ROUND_HALF_UP)
    montant_arrete_raw = base_indemnite - franchise - remise
    montant_arrete = (montant_arrete_raw if montant_arrete_raw > 0 else Decimal("0.00")).quantize(
        _CENT, rounding=ROUND_HALF_UP
    )

    return {
        "montant_charge_mutuelle": str(charge_mutuelle),
        "montant_charge_societaire": str(charge_societaire),
        "total_tva": str(total_tva),
        "total_ttc": str(total_ttc),
        "vetuste": str(vetuste),
        "franchise": str(franchise),
        "remise": str(remise),
        "montant_arrete": str(montant_arrete),
        "base_indemnite": str(base_indemnite),
    }


def _simulate_native_calc(workflow: str, payload: dict) -> dict:
    """Unchanged legacy (INC-06) shape/behavior for MODE_NORMAL -- writer.py
    never calls this endpoint for MODE_NORMAL (trigger_native_recalc()
    always raises NativeCalculationUnconfirmed for it; see
    mcma.portal.writer's module docstring), so this branch is retained
    exactly as-is, still exercised only by tests/mock/*'s own pre-existing
    coverage.

    For GARAGE_CONVENTIONNE, the response is now a SUPERSET of the
    original shape (INC-09B amendment #2): the original `summary`/`stale`
    fields are preserved byte-for-byte for tests/mock/
    test_mock_server_readiness_simulation.py and
    test_mock_server_pec_workflow.py's own pre-existing "summary" shaped
    assertions; `calculation_version`/`expected`/`apply_to_dom` are ADDED
    for mcma.portal.writer's independent two-channel verification (an
    HTTP-response-carried `expected` FinancialSummary compared against a
    SEPARATE, later, fresh DOM read -- never the same value read twice).
    Two new simulate modes are added for GARAGE_CONVENTIONNE only:
    "malformed" (a field that will not parse as Money) and "incomplete"
    (a required field is entirely absent) -- both distinct, fail-closed
    classifications from "failed"/"missing"/"stale"/"mismatch"."""
    guard = _reject_if_charge_fields_present(payload, workflow)
    if guard is not None:
        return {
            "state": "error",
            "reason": "DIRECT_CHARGE_FIELD_WRITE_REJECTED",
            "fields": sorted(ALL_CHARGE_FIELDS.intersection(payload.keys())),
        }

    obs = MOCK_STATE["observability"]
    obs["native_calculation_calls"][workflow] += 1

    simulate = payload.get("simulate", "success")
    total_ttc = _to_float(payload.get("total_ttc"))
    franchise = _to_float(payload.get("franchise"))
    vetuste = _to_float(payload.get("vetuste"))
    remise = _to_float(payload.get("remise"))
    part_resp = _to_float(payload.get("part_resp"), 100.0)

    charge_soc = round(franchise * part_resp / 100.0 + vetuste, 2)
    charge_mut = round(max(0.0, total_ttc - charge_soc - remise), 2)

    if simulate == "failed":
        return {"state": "error", "reason": "NATIVE_CALCULATION_FAILED"}

    if simulate == "missing":
        return {"state": "error", "reason": "MISSING_CALCULATION_RESULT"}

    if workflow == "GARAGE_CONVENTIONNE" and simulate == "malformed":
        # A real calculation attempt happened (its own generation still
        # advances) -- only the RESULT is malformed. Using an
        # un-advanced (possibly still-zero, on a fresh writer's very
        # first trigger) version here would make
        # _require_valid_calculation_version reject it before the
        # malformed `expected` value is ever even parsed, masking the
        # intended failure classification behind an unrelated one.
        obs["calculation_version"][workflow] += 1
        expected = _compute_pec_financial_summary(payload)
        malformed = dict(expected)
        malformed["total_ttc"] = "not-a-number"
        return {
            "state": "success",
            "calculation_version": obs["calculation_version"][workflow],
            "expected": malformed,
            "apply_to_dom": malformed,
        }

    if workflow == "GARAGE_CONVENTIONNE" and simulate == "incomplete":
        obs["calculation_version"][workflow] += 1
        expected = _compute_pec_financial_summary(payload)
        incomplete = dict(expected)
        del incomplete["base_indemnite"]
        return {
            "state": "success",
            "calculation_version": obs["calculation_version"][workflow],
            "expected": incomplete,
            "apply_to_dom": incomplete,
        }

    if simulate == "stale":
        previous = MOCK_STATE["financial_summary"][workflow]
        version = obs["calculation_version"][workflow]
        if previous is None:
            previous = {
                "charge_mutuelle": 0.0,
                "charge_societaire": 0.0,
                "calculation_version": version,
            }
        stale_summary = dict(previous)
        stale_summary["stale"] = True
        MOCK_STATE["financial_summary"][workflow] = stale_summary
        MOCK_STATE["mismatch_injected"][workflow] = False
        expected = _compute_pec_financial_summary(payload) if workflow == "GARAGE_CONVENTIONNE" else None
        result = {"state": "success", "stale": True, "summary": stale_summary}
        if expected is not None:
            # Deliberately does NOT advance calculation_version -- this is
            # exactly what a fresh trigger should never look like.
            result["calculation_version"] = version
            result["expected"] = expected
            result["apply_to_dom"] = expected
        return result

    obs["calculation_version"][workflow] += 1
    version = obs["calculation_version"][workflow]

    computed = {
        "charge_mutuelle": charge_mut,
        "charge_societaire": charge_soc,
        "calculation_version": version,
        "stale": False,
    }

    if simulate == "mismatch":
        corrupted = dict(computed)
        corrupted["charge_mutuelle"] = round(charge_mut + 1.0, 2)
        MOCK_STATE["financial_summary"][workflow] = corrupted
        MOCK_STATE["mismatch_injected"][workflow] = True
        result = {"state": "success", "summary": computed}
        if workflow == "GARAGE_CONVENTIONNE":
            expected = _compute_pec_financial_summary(payload)
            apply_to_dom = dict(expected)
            apply_to_dom["montant_charge_mutuelle"] = str(
                (Decimal(expected["montant_charge_mutuelle"]) + Decimal("1.00")).quantize(
                    _CENT, rounding=ROUND_HALF_UP
                )
            )
            result["calculation_version"] = version
            result["expected"] = expected
            result["apply_to_dom"] = apply_to_dom
        return result

    # success
    MOCK_STATE["financial_summary"][workflow] = computed
    MOCK_STATE["mismatch_injected"][workflow] = False
    result = {"state": "success", "summary": computed}
    if workflow == "GARAGE_CONVENTIONNE":
        expected = _compute_pec_financial_summary(payload)
        result["calculation_version"] = version
        result["expected"] = expected
        result["apply_to_dom"] = expected
    return result


# ---------------------------------------------------------------------------
# Static, fully offline vanilla-JS/CSS mission page
# ---------------------------------------------------------------------------

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <title>MCMA - SinAuto Expertise (Local Mock Server)</title>
    <style>
        body { font-family: Arial, Helvetica, sans-serif; background-color: #f4f6f9; color: #333; font-size: 12px; margin: 0; }
        .navbar { background-color: #003366; color: white; padding: 12px 20px; font-size: 18px; font-weight: bold; }
        .mission-header { background: #fff; border-bottom: 2px solid #ddd; padding: 10px 20px; margin-bottom: 15px; }
        .badge-statut { background-color: #5cb85c; color: white; padding: 3px 8px; font-size: 11px; border-radius: 3px; }
        fieldset { border: 1px solid #c0c0c0; margin: 0 20px 15px 20px; padding: 10px 15px; background: #fff; border-radius: 4px; }
        legend { font-size: 13px; font-weight: bold; color: #003366; padding: 0 8px; }
        .form-row { margin-bottom: 8px; }
        .form-row label { display: inline-block; width: 160px; font-weight: 600; }
        input[type=text], select, textarea { padding: 3px 6px; font-size: 12px; border-radius: 2px; border: 1px solid #ccc; }
        table { border-collapse: collapse; width: 100%; margin-bottom: 8px; }
        table th, table td { border: 1px solid #ddd; padding: 4px 6px; font-size: 11px; text-align: left; }
        table th { background: #eee; }
        .text-right { text-align: right; }
        .btn { display: inline-block; padding: 4px 10px; font-size: 11px; border-radius: 3px; cursor: pointer; border: 1px solid #999; background: #eee; }
        .btn-success { background: #5cb85c; color: white; border-color: #4cae4c; }
        .btn-check { color: #5cb85c; cursor: pointer; font-weight: bold; font-size: 14px; }
        .btn-pencil { color: #337ab7; cursor: pointer; font-size: 13px; }
        .tr-editing { background-color: #e8f4ff; }
        .summary-box { background: #fafafa; padding: 10px; border-radius: 4px; margin-top: 10px; }
        .hud-log { background: #222; color: #00ff66; font-family: monospace; font-size: 11px; padding: 10px; max-height: 120px; overflow-y: auto; border-top: 2px solid #444; }
        .mock-only-note { color: #a94442; font-size: 10px; font-style: italic; }
    </style>
</head>
<body data-page-marker="expert_.phtml">

    <div class="navbar">SinAuto MCMA - Espace Gestion Expert (Local Offline Mock)</div>

    <div class="mission-header">
        <span id="hdrRefSinistre"><b>Ref Sinistre:</b> __REF_SINISTRE__</span>
        &nbsp;|&nbsp;
        <span id="hdrMatricule"><b>Matricule:</b> __MATRICULE__</span>
        &nbsp;|&nbsp;
        <span class="badge-statut">DECLARE</span>
    </div>

    <form id="formExpertMission" onsubmit="return false;">
        <input type="hidden" id="IdSinistre__I" value="__ID_SINISTRE__">
        <input type="hidden" id="IdMission" value="__ID_MISSION__">
        <input type="hidden" id="MatriculeVeh" value="__MATRICULE__">

        <fieldset>
            <legend>Options</legend>
            <label><input type="checkbox" id="VehRepareI" checked> Vehicule Repare</label>
            <label><input type="checkbox" id="DevisTvaRecupI" checked> TVA Recuperable</label>
        </fieldset>

        <!-- Correction batch (pilot-integration, section 7): the five
             recovered non-table header fields (PORTAL_CONTRACT.md §4-5)
             this project has confirmed evidence for -- shared across both
             workflows regardless of mode, per that same section. -->
        <fieldset>
            <legend>Informations vehicule / mission</legend>
            <label>Kilometrage:</label> <input type="text" id="Kilometrage" value="0">
            <label>Valeur Venale:</label> <input type="text" id="ValeurVenale" value="0">
            <label>Valeur Venale Estimee:</label> <input type="text" id="ValeurVenaleEstime" value="0">
            <label>Nbre Jour Immobilisation:</label> <input type="text" id="NbreJourImmobilisation" value="0">
            <label>Part Responsabilite:</label>
            <select id="PartResponsabilite">
                <option value="0">0</option>
                <option value="50">50</option>
                <option value="100">100</option>
            </select>
            <br><br>
            <label>Observation Mission:</label><br>
            <textarea id="ObservationMission" rows="3" cols="60"></textarea>
        </fieldset>

        <!-- ================= GARAGE CONVENTIONNE / PEC ================= -->
        <div id="sectionGarageConventionne">
            <fieldset>
                <legend>Devis de la reparation (Garage - Lecture Seule)</legend>
                <table id="DevisDetTable">
                    <thead><tr><th>Rubrique</th><th class="text-right">Montant HT</th><th class="text-right">MT Taxe</th><th class="text-right">Montant TTC</th></tr></thead>
                    <tbody id="tbodyDevisTable1">
__PEC_ORIGINAL_ROWS__
                    </tbody>
                </table>
            </fieldset>

            <fieldset id="blocDevisValide">
                <legend>Devis de la reparation valide (Expert - Modifiable)</legend>
                <table id="DevisDetTableVal">
                    <thead>
                        <tr><th>Rubrique</th><th class="text-right">HT</th><th class="text-right">Taxe</th><th class="text-right">TTC</th><th class="text-right">Taux Vet.</th><th class="text-right">Mt Vet.</th><th></th></tr>
                    </thead>
                    <tbody id="tbodyDevisTable2"></tbody>
                </table>

                <div class="summary-box">
                    <!-- Golden PEC summary ids (8e5e4e6). These replace the
                         [data-mock-only-*] attributes the previous mock used:
                         the golden implementation read #DevisMontantTVA,
                         #DevisMontantTTC, #DevisMontantVetusteTotal,
                         #DevisMontantFranchise, #DevisMontantRemise and
                         #DevisPartResponsabilite against the real portal, so
                         they are recovered selectors rather than invented
                         ones and production reads them directly. -->
                    <label>Devis TTC:</label> <input type="text" id="DevisMontantTTC" value="11200.00" readonly>
                    <label>Devis TVA:</label> <input type="text" id="DevisMontantTVA" value="1866.67" readonly>
                    <label>Vetuste Total:</label> <input type="text" id="DevisMontantVetusteTotal" value="0.00">
                    <label>Franchise:</label> <input type="text" id="DevisMontantFranchise" value="0.00">
                    <label>Remise:</label> <input type="text" id="DevisMontantRemise" value="0.00">
                    <label>Part Responsabilite:</label> <input type="text" id="DevisPartResponsabilite" value="0.00">
                    <label>Montant Arrete:</label> <input type="text" id="MontantArrete" value="0.00" readonly>
                    <label>Base Indemnite:</label> <input type="text" id="BaseIndemnite" value="0.00" readonly>
                    <br><br>
                    <label>Charge Societaire:</label>
                    <input type="text" id="DevisMontantChargeSocietaire" value="0.00" disabled>
                    <label>Charge Mutuelle:</label>
                    <input type="text" id="DevisMontantChargeMutuelle" value="0.00" disabled>
                    <div class="mock-only-note">DevisCalculerMontantCharge() is the confirmed PEC client-side function, recovered from 8e5e4e6 and exercised against real dossiers. Production now invokes it in the page and reads the ids above; the old HTTP mirror (/_mock/pec/native_calculation) and its calculation_version envelope were mock-only and are no longer part of the production path.</div>
                    <select id="mockSimulatePec"><option value="success">success</option><option value="stale">stale</option><option value="missing">missing</option><option value="failed">failed</option><option value="malformed">malformed</option><option value="incomplete">incomplete</option><option value="mismatch">mismatch</option></select>
                </div>

                <div style="text-align:right; margin-top:10px;">
                    <a id="DEVISDET_Btn" class="btn btn-success" onclick="ValiderDevis()">Valider Devis (permanently prohibited)</a>
                </div>
            </fieldset>
        </div>

        <!-- ================= MODE NORMAL ================= -->
        <div id="sectionModeNormal" style="display:none;">
            <fieldset>
                <legend>Rapport d'expertise de reparation (Mode Normal)</legend>
                <a class="btn btn-success" onclick="ajouterLigneModeNormal()">Ajouter +</a>
                <table id="tableRapportDet">
                    <thead>
                        <tr><th>Rubrique</th><th class="text-right">HT</th><th class="text-right">Taxe</th><th class="text-right">TTC</th><th class="text-right">Taux Vet.</th><th class="text-right">Mt Vet.</th><th>Action</th></tr>
                    </thead>
                    <tbody id="tbodyModeNormal"></tbody>
                </table>

                <div class="summary-box">
                    <!-- Golden Mode Normal summary ids (9a2c57c). The driver
                         reads exactly this set after invoking the portal's own
                         Calculer* functions; MontantTVA, MontantTTC, MontantRemise,
                         MontantArrete and BaseIndemnite were missing from this
                         mock entirely, so the summary could not be read at all. -->
                    <label>Mt Reparation:</label> <input type="text" id="MontantReparation" value="0.00">
                    <label>Mt TVA:</label> <input type="text" id="MontantTVA" value="0.00">
                    <label>Mt TTC:</label> <input type="text" id="MontantTTC" value="0.00">
                    <label>Franchise:</label> <input type="text" id="MontantFranchise" value="0.00">
                    <label>Remise:</label> <input type="text" id="MontantRemise" value="0.00">
                    <label>Vetuste Total:</label> <input type="text" id="MontantVetusteTotal" value="0.00">
                    <label>Mt Arrete:</label> <input type="text" id="MontantArrete" value="0.00" readonly>
                    <label>Base Indemnite:</label> <input type="text" id="BaseIndemnite" value="0.00" readonly>
                    <br><br>
                    <label>Charge Societaire:</label>
                    <input type="text" id="MontantChargeSocietaire" value="0.00" disabled>
                    <label>Charge Mutuelle:</label>
                    <input type="text" id="MontantChargeMutuelle" value="0.00" disabled>
                    <div class="mock-only-note">UNCONFIRMED live contract (docs/architecture/PORTAL_ROW_WORKFLOWS.md 3.1). The button below calls a MOCK-ONLY test hook only -- it is never a confirmed selector or endpoint and is never eligible for any live allowlist.</div>
                    <a class="btn" onclick="mockOnlyTriggerNormalNativeCalculation()">MOCK-ONLY native calc (UNCONFIRMED)</a>
                    <select id="mockSimulateNormal"><option value="success">success</option><option value="stale">stale</option><option value="missing">missing</option><option value="failed">failed</option><option value="mismatch">mismatch</option></select>
                </div>
            </fieldset>
        </div>
    </form>

    <div class="hud-log" id="hudLog"><div>[MOCK MCMA SERVER ONLINE - fully offline, no external resources]</div></div>

    <script>
    function logHUD(msg) {
        var el = document.getElementById("hudLog");
        var line = document.createElement("div");
        line.textContent = msg;
        el.appendChild(line);
        el.scrollTop = el.scrollHeight;
    }

    function postForm(url, fields) {
        var body = new URLSearchParams();
        for (var k in fields) { body.append(k, fields[k]); }
        return fetch(url, { method: "POST", body: body }).then(function(r) { return r.json(); });
    }

    function postJson(url, obj) {
        return fetch(url, { method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(obj) })
            .then(function(r) { return r.json(); });
    }

    function reportFieldEvent(workflow, rowId, field, eventType) {
        postJson("/_mock/field_event", {workflow: workflow, row_id: rowId, field: field, event_type: eventType});
    }

    function wireFieldEvents(input, workflow, rowId, field) {
        ["input", "change", "blur"].forEach(function(evt) {
            input.addEventListener(evt, function() { reportFieldEvent(workflow, rowId, field, evt); });
        });
    }

    // ---------------- INC-09B amendment #3: exact BigInt/HALF_UP
    // arithmetic for every financial calculation this mock's own
    // client-side JS performs. Never Number/parseFloat/Math.round/binary
    // floating-point division on a monetary or percentage value. ----------

    function parseMoneyToCents(str) {
        if (typeof str !== "string") { throw new Error("not a string"); }
        var s = str.trim();
        var m = /^(-?)(\\d+)(?:\\.(\\d{1,2}))?$/.exec(s);
        if (!m) { throw new Error("malformed monetary string: " + str); }
        var sign = m[1] === "-" ? -1n : 1n;
        var intPart = BigInt(m[2]);
        var fracStr = (m[3] || "").padEnd(2, "0");
        var fracPart = BigInt(fracStr);
        return sign * (intPart * 100n + fracPart);
    }

    function centsToMoneyString(cents) {
        var neg = cents < 0n;
        var abs = neg ? -cents : cents;
        var intPart = abs / 100n;
        var fracPart = abs % 100n;
        var fracStr = fracPart.toString().padStart(2, "0");
        return (neg ? "-" : "") + intPart.toString() + "." + fracStr;
    }

    function halfUpDivideBigInt(numerator, denominator) {
        if (denominator === 0n) { throw new Error("division by zero"); }
        var quotient = numerator / denominator;
        var remainder = numerator % denominator;
        return quotient + (2n * remainder >= denominator ? 1n : 0n);
    }

    function recomputeNormalTtc(tempId) {
        // Unsuffixed, like the editing row itself.
        var ttcInput = document.getElementById("MontantTTCLigne");
        if (!ttcInput) { return; }
        try {
            var ht = parseMoneyToCents(document.getElementById("MontantHT").value || "0");
            var taxe = parseMoneyToCents(document.getElementById("Taxe").value || "0");
            ttcInput.value = centsToMoneyString(ht + taxe);
        } catch (e) {
            ttcInput.value = "";
        }
    }

    function recomputePecDerived(id) {
        var ttcInput = document.getElementById("MontantTTCValide");
        var rateInput = document.getElementById("TauxVetusteValide");
        try {
            var ht = parseMoneyToCents(document.getElementById("MontantHTValide").value || "0");
            var taxe = parseMoneyToCents(document.getElementById("TaxeValide").value || "0");
            var ttcCents = ht + taxe;
            ttcInput.value = centsToMoneyString(ttcCents);
            var vetusteCents = parseMoneyToCents(document.getElementById("MontantVetusteValide").value || "0");
            if (ttcCents === 0n) {
                // Undefined derivation -- left blank, never coerced to "0.00".
                rateInput.value = "";
            } else {
                var numerator = vetusteCents * 10000n; // amount/ttc*100, scaled for a 2dp percentage
                var rateHundredths = halfUpDivideBigInt(numerator, ttcCents);
                rateInput.value = centsToMoneyString(rateHundredths);
            }
        } catch (e) {
            ttcInput.value = "";
            rateInput.value = "";
        }
    }

    // ---------------- Mode Normal ----------------
    var normalTempCounter = 0;

    function ajouterLigneModeNormal() {
        // Golden shape (9a2c57c): the portal shows ONE editing row at a
        // time carrying UNSUFFIXED ids, and it is saved by the control in
        // the 7th column. The previous mock issued #IdRubrique_<tempId>
        // and a text="OK" link; neither exists on the real portal.
        if (document.querySelector("#MontantHT")) {
            logHUD("Mode Normal: an editing row is already open.");
            return;
        }
        normalTempCounter++;
        var tempId = "tmp-" + normalTempCounter;
        var tr = document.createElement("tr");
        tr.className = "tr-editing";
        tr.setAttribute("data-temp-id", tempId);

        var rubTd = document.createElement("td");
        var sel = document.createElement("select");
        [["1","FOURNITURES CARROSSERIE (ORIGINES)"],["3","TOTAL PIECES OCCASIONS / RECUPERABLES"],["7","MAIN D'OEUVRE CARROSSERIE"],["12","MAIN D'OEUVRE PEINTURE"],["16","PEINTURES ET INGREDIENTS"]].forEach(function(o) {
            var opt = document.createElement("option"); opt.value = o[0]; opt.textContent = o[1]; sel.appendChild(opt);
        });
        sel.id = "IdRubrique";
        sel.name = "IdRubrique";
        wireFieldEvents(sel, "MODE_NORMAL", tempId, "IdRubrique");
        rubTd.appendChild(sel); tr.appendChild(rubTd);

        ["MontantHT", "Taxe", "TauxVetuste", "MontantVetuste"].forEach(function(field) {
            var td = document.createElement("td");
            var input = document.createElement("input");
            input.type = "text";
            input.id = field;
            input.name = field;
            input.value = field === "MontantHT" || field === "Taxe" ? "" : "0.00";
            wireFieldEvents(input, "MODE_NORMAL", tempId, field);
            if (field === "MontantHT" || field === "Taxe") {
                input.addEventListener("input", function() { recomputeNormalTtc(tempId); });
                input.addEventListener("change", function() { recomputeNormalTtc(tempId); });
            }
            td.appendChild(input); tr.appendChild(td);
        });

        var ttcTd = document.createElement("td");
        var ttcInput = document.createElement("input");
        ttcInput.type = "text"; ttcInput.id = "MontantTTCLigne"; ttcInput.readOnly = true; ttcInput.value = "0.00";
        ttcTd.appendChild(ttcInput); tr.appendChild(ttcTd);

        // 7th column. The driver clicks td:nth-child(7) or its clickable
        // descendant, so the control must live exactly here.
        var actionTd = document.createElement("td");
        var check = document.createElement("a");
        check.className = "btn-check";
        var checkIcon = document.createElement("i");
        checkIcon.className = "fa-check";
        checkIcon.textContent = "\u2713";
        check.appendChild(checkIcon);
        check.onclick = function() { saveNormalRow(tempId); };
        actionTd.appendChild(check); tr.appendChild(actionTd);

        document.getElementById("tbodyModeNormal").prepend(tr);
        logHUD("Mode Normal: Ajouter + opened one editing row with unsuffixed ids.");
    }

    function saveNormalRow(tempId) {
        var rubSel = document.getElementById("IdRubrique");
        if (!rubSel) { return; }
        var fields = {
            IdRubrique: rubSel.value,
            MontantHT: document.getElementById("MontantHT").value || "0.00",
            Taxe: document.getElementById("Taxe").value || "0.00",
            MontantTTC: document.getElementById("MontantTTCLigne").value || "0.00",
            TauxVetuste: document.getElementById("TauxVetuste").value || "0.00",
            MontantVetuste: document.getElementById("MontantVetuste").value || "0.00",
            TempRowId: tempId
        };
        // The mock still records the call for observability, but the DOM
        // commit below does NOT depend on it: production no longer requires
        // a createRapportDefDet response, because the golden Mode Normal
        // never observed one.
        postForm("/SinAuto_MCMA/expertise/gestionExpert/createRapportDefDet", fields).then(function(res) {
            if (res.state === "success") {
                logHUD("createRapportDefDet OK -> rubrique " + fields.IdRubrique + " committed.");
                refreshNormalTable();
            } else {
                logHUD("createRapportDefDet REJECTED: " + res.reason);
            }
        });
    }

    function refreshNormalTable() {
        postForm("/SinAuto_MCMA/expertise/gestionExpert/listeRapportDefDet", {}).then(function(res) {
            var tbody = document.getElementById("tbodyModeNormal");
            tbody.innerHTML = "";
            (res.data || []).forEach(function(row) {
                var tr = document.createElement("tr");
                tr.id = "normal_saved_" + row.IdRapportDefDet;
                ["IdRubrique", "MontantHT", "Taxe", "MontantTTC", "TauxVetuste", "MontantVetuste"].forEach(function(f) {
                    var td = document.createElement("td"); td.textContent = row[f]; tr.appendChild(td);
                });
                var actionTd = document.createElement("td"); actionTd.textContent = "saved"; tr.appendChild(actionTd);
                tbody.appendChild(tr);
            });
        });
    }

    function mockOnlyTriggerNormalNativeCalculation() {
        var payload = {
            total_ttc: document.getElementById("MontantReparation").value || "0",
            franchise: document.getElementById("MontantFranchise").value || "0",
            vetuste: document.getElementById("MontantVetusteTotal").value || "0",
            remise: "0",
            part_resp: "100",
            simulate: document.getElementById("mockSimulateNormal").value
        };
        postJson("/_mock/normal/native_calculation", payload).then(function(res) {
            if (res.state === "success" && res.summary) {
                document.getElementById("MontantChargeMutuelle").value = res.summary.charge_mutuelle;
                document.getElementById("MontantChargeSocietaire").value = res.summary.charge_societaire;
                logHUD("MOCK-ONLY normal native calculation (" + payload.simulate + ") executed.");
            } else {
                logHUD("MOCK-ONLY normal native calculation FAILED: " + res.reason);
            }
        });
    }

    // ---------------- Garage Conventionne / PEC ----------------
    var pecNonceCounter = 0;

    function renderTable2(rows) {
        var tbody = document.getElementById("tbodyDevisTable2");
        tbody.innerHTML = "";
        rows.forEach(function(item) {
            var tr = document.createElement("tr");
            // Golden shape (8e5e4e6): the row is identified by its
            // DISPLAYED LABEL, not by an id the real table does not carry.
            // data-id-devis-det is kept only so the mock's own save
            // endpoint still has something to key on.
            tr.setAttribute("data-id-devis-det", item.IdDevisDet);
            var labelTd = document.createElement("td"); labelTd.textContent = item.LibRubrique; tr.appendChild(labelTd);
            ["MontantHT", "Taxe", "MontantTTC", "TauxVetuste", "MontantVetuste"].forEach(function(f) {
                var td = document.createElement("td"); td.className = "text-right col-" + f; td.textContent = item[f]; tr.appendChild(td);
            });
            var actionTd = document.createElement("td");
            var pencil = document.createElement("a");
            // Golden pencil selector family.
            pencil.className = "btn-pencil edit-row";
            pencil.setAttribute("title", "Modifier");
            var pencilIcon = document.createElement("i");
            pencilIcon.className = "fa-pencil";
            pencilIcon.textContent = "\u270e";
            pencil.appendChild(pencilIcon); pencil.onclick = (function(id) { return function() { editRowTable2(id); }; })(item.IdDevisDet);
            actionTd.appendChild(pencil); tr.appendChild(actionTd);
            tbody.appendChild(tr);
        });
    }

    function refreshPecTable() {
        postForm("/SinAuto_MCMA/expertise/gestiongarage/listeDevisDet", {}).then(function(res) {
            renderTable2(res.data || []);
        });
    }

    function editRowTable2(id) {
        var tr = document.querySelector('#DevisDetTableVal tbody tr[data-id-devis-det="' + id + '"]');
        if (!tr) { return; }
        tr.classList.add("tr-editing");
        ["MontantHT", "Taxe"].forEach(function(f) {
            var td = tr.querySelector(".col-" + f);
            var current = td.textContent;
            td.innerHTML = "";
            var input = document.createElement("input");
            input.type = "text"; input.id = f + "Valide"; input.name = f + "Valide"; input.value = current;
            wireFieldEvents(input, "GARAGE_CONVENTIONNE", String(id), f);
            input.addEventListener("input", function() { recomputePecDerived(id); });
            input.addEventListener("change", function() { recomputePecDerived(id); });
            td.appendChild(input);
        });
        // MontantTTCValide did not exist before INC-09B -- it is a
        // readonly field derived from HT+Taxe (never directly filled by
        // the writer), matching PORTAL_ROW_WORKFLOWS.md 2's "verify the
        // computed #MontantTTCValide where exposed" step.
        var ttcTd = tr.querySelector(".col-MontantTTC");
        var ttcCurrent = ttcTd.textContent;
        ttcTd.innerHTML = "";
        var ttcInput = document.createElement("input");
        ttcInput.type = "text"; ttcInput.id = "MontantTTCValide"; ttcInput.readOnly = true; ttcInput.value = ttcCurrent;
        ttcTd.appendChild(ttcInput);
        ["TauxVetuste", "MontantVetuste"].forEach(function(f) {
            var td = tr.querySelector(".col-" + f);
            var current = td.textContent;
            td.innerHTML = "";
            var input = document.createElement("input");
            input.type = "text"; input.id = f + "Valide"; input.name = f + "Valide"; input.value = current;
            if (f === "TauxVetuste") { input.readOnly = true; }
            wireFieldEvents(input, "GARAGE_CONVENTIONNE", String(id), f);
            if (f === "MontantVetuste") {
                input.addEventListener("input", function() { recomputePecDerived(id); });
                input.addEventListener("change", function() { recomputePecDerived(id); });
            }
            td.appendChild(input);
        });
        recomputePecDerived(id);
        var actionTd = tr.querySelector("td:last-child");
        actionTd.innerHTML = "";
        var check = document.createElement("a");
        check.className = "btn-check save-row";
        check.setAttribute("title", "Enregistrer");
        var checkIcon = document.createElement("i");
        checkIcon.className = "fa-check";
        checkIcon.textContent = "\u2713";
        check.appendChild(checkIcon);
        check.onclick = function() { saveRowTable2(id); };
        actionTd.appendChild(check);
        logHUD("PEC: row " + id + " entered edit mode (exact row only).");
    }

    function saveRowTable2(id) {
        pecNonceCounter++;
        var fields = {
            IdDevisDet: id,
            MontantHTValide: document.getElementById("MontantHTValide").value,
            TaxeValide: document.getElementById("TaxeValide").value,
            MontantTTCValide: document.getElementById("MontantTTCValide") ? document.getElementById("MontantTTCValide").value : "0.00",
            TauxVetusteValide: document.getElementById("TauxVetusteValide").value,
            MontantVetusteValide: document.getElementById("MontantVetusteValide").value,
            SubmissionNonce: "pec-" + id + "-" + pecNonceCounter
        };
        postForm("/SinAuto_MCMA/expertise/gestionexpert/updateDevisDet", fields).then(function(res) {
            if (res.state === "success") {
                logHUD("updateDevisDet OK -> row " + id + " saved.");
                refreshPecTable();
            } else {
                logHUD("updateDevisDet REJECTED: " + res.reason);
            }
        });
    }

    function DevisCalculerMontantCharge() {
        var payload = {
            total_ttc: document.getElementById("DevisMontantTTC").value || "0",
            total_tva: document.getElementById("DevisMontantTVA").value || "0",
            franchise: document.getElementById("DevisMontantFranchise").value || "0",
            vetuste: document.getElementById("DevisMontantVetusteTotal").value || "0",
            remise: document.getElementById("DevisMontantRemise").value || "0",
            part_resp: "100",
            simulate: document.getElementById("mockSimulatePec").value
        };
        postJson("/_mock/pec/native_calculation", payload).then(function(res) {
            if (res.state === "success" && res.apply_to_dom) {
                var applied = res.apply_to_dom;
                document.getElementById("DevisMontantChargeMutuelle").value = applied.montant_charge_mutuelle;
                document.getElementById("DevisMontantChargeSocietaire").value = applied.montant_charge_societaire;
                document.getElementById("DevisMontantTVA").value = applied.total_tva;
                document.getElementById("DevisMontantTTC").value = applied.total_ttc;
                document.getElementById("DevisMontantVetusteTotal").value = applied.vetuste;
                document.getElementById("DevisMontantFranchise").value = applied.franchise;
                document.getElementById("DevisMontantRemise").value = applied.remise;
                if (applied.montant_arrete !== undefined) { document.getElementById("MontantArrete").value = applied.montant_arrete; }
                if (applied.base_indemnite !== undefined) { document.getElementById("BaseIndemnite").value = applied.base_indemnite; }
                logHUD("DevisCalculerMontantCharge() (" + payload.simulate + ") executed.");
            } else {
                logHUD("DevisCalculerMontantCharge() " + (res.state === "success" ? "SUCCEEDED WITHOUT apply_to_dom" : "FAILED: " + res.reason));
            }
        });
    }

    function ValiderDevis() {
        postForm("/SinAuto_MCMA/expertise/gestiongarage/garageModifierValDevis", {}).then(function(res) {
            logHUD("Valider Devis -> " + res.reason + " (permanently prohibited; DOM unchanged).");
        });
    }

    document.addEventListener("DOMContentLoaded", function() {
        refreshPecTable();
        logHUD("DOM loaded; no external resources fetched.");
    });
    </script>
</body>
</html>
"""


def _render_pec_original_rows() -> str:
    rows = MOCK_STATE["rows"]["pec_original"]
    parts = []
    for row in rows:
        parts.append(
            "<tr><td>{lib}</td><td class=\"text-right\">{ht}</td><td class=\"text-right\">{taxe}</td><td class=\"text-right\">{ttc}</td></tr>".format(
                lib=row["LibRubrique"], ht=row["MontantHT"], taxe=row["Taxe"], ttc=row["MontantTTC"]
            )
        )
    return "\n".join(parts)


def _strip_section(html: str, section_id: str) -> str:
    """Removes the <div id="{section_id}">...</div> block ENTIRELY
    (balanced-tag scan, not a naive first-</div> cut -- both sections
    contain their own nested <div> elements) -- not merely hidden, so a
    document.querySelector for a marker inside it finds nothing, not just
    something invisible. Used only by the mock-only ?workflow= parameter
    below (INC-09A)."""
    start_marker = f'<div id="{section_id}"'
    start = html.index(start_marker)
    pos = html.index(">", start) + 1
    depth = 1
    while depth > 0:
        next_open = html.find("<div", pos)
        next_close = html.find("</div>", pos)
        if next_close == -1:
            raise ValueError(f"unbalanced <div> while stripping {section_id!r}")
        if next_open != -1 and next_open < next_close:
            depth += 1
            pos = next_open + 4
        else:
            depth -= 1
            pos = next_close + len("</div>")
    return html[:start] + html[pos:]


# The baseline PEC mission's identity, preserved byte-for-byte as the
# DEFAULT rendering for every caller that never passes `identity=` --
# INC-09A's own accepted real-Chromium proofs navigate the bare
# ?workflow= query route and depend on exactly these values.
_DEFAULT_IDENTITY = {
    "id_sinistre": "534660",
    "id_mission": "532805",
    "matricule": "34602-B-7",
    "ref_sinistre": "MEX202648130",
}


def _render_mission_page(workflow: str | None = None, identity: dict | None = None) -> str:
    """`workflow` is MOCK-ONLY test infrastructure (INC-09A), never a
    confirmed live query parameter or contract -- see
    tests/fixtures/contracts/ for how every genuinely confirmed contract in
    this project is classified; this parameter is not one of them.

    None (the default, unspecified) renders BOTH sections exactly as the
    baseline INC-06 page always has (PEC visible, Mode Normal present at
    display:none) -- this is unchanged, existing behavior, preserved
    byte-for-byte for any caller that never passes it.
    "normal" or "conventionne" REMOVES the other section's markup entirely
    (not just hides it) so a real browser's document.querySelector can
    distinguish "workflow section absent" from "present but invisible" --
    needed for INC-09A's workflow-detection gate (mcma.portal.mission).
    For "normal" specifically, the leftover `style="display:none;"` on
    #sectionModeNormal (present in the always-both-sections HTML_TEMPLATE,
    where Mode Normal starts hidden pending #VehRepareI) is ALSO removed:
    Mode Normal is now the sole/active workflow being rendered, not a
    hidden alternative -- a real Playwright click needs the element to
    actually be visible (found the hard way: a real-Chromium proof timed
    out clicking Ajouter under the un-fixed display:none). Detection via
    document.querySelector is unaffected either way (hidden elements are
    still found by it), so this fix does not change 09A's own accepted
    workflow-detection proof, which never asserted visibility.

    `identity` (INC-09B amendment #2 fix) substitutes the rendered
    IdMission/IdSinistre__I/MatriculeVeh/header-text -- defaults to the
    original fixed PEC identity so every pre-existing caller (including
    the bare ?workflow= route used by 09A's own accepted tests) is
    completely unaffected."""
    identity = identity or _DEFAULT_IDENTITY
    html = HTML_TEMPLATE.replace("__PEC_ORIGINAL_ROWS__", _render_pec_original_rows())
    html = html.replace("__ID_SINISTRE__", str(identity["id_sinistre"]))
    html = html.replace("__ID_MISSION__", str(identity["id_mission"]))
    html = html.replace("__MATRICULE__", str(identity["matricule"]))
    html = html.replace("__REF_SINISTRE__", str(identity["ref_sinistre"]))
    if workflow == "normal":
        html = _strip_section(html, "sectionGarageConventionne")
        html = html.replace(
            '<div id="sectionModeNormal" style="display:none;">', '<div id="sectionModeNormal">'
        )
    elif workflow == "conventionne":
        html = _strip_section(html, "sectionModeNormal")
    return html


# ---------------------------------------------------------------------------
# Route handlers -- mission page, auth/session, notifications
# ---------------------------------------------------------------------------


@app.get("/")
@app.get("/SinAuto_MCMA/expertise/gestionexpert/index")
@app.get("/SinAuto_MCMA/expertise/gestionExpert/index")
def get_mission_page(workflow: str | None = None):
    return HTMLResponse(content=_render_mission_page(workflow))


@app.get("/SinAuto_MCMA/expertise/gestionExpert/getSinistre/idSinistre/{id_value}/rubrique/gestionexpert-index")
def get_mission_deep_link(id_value: str):
    """INC-09B amendment #2: mcma.portal.mission's accepted (09A)
    open_candidate() substitutes candidate.id_mission into this route's
    {id_sinistre}-named placeholder -- MissionCandidate has no id_sinistre
    field at all, so the value that actually arrives here is id_mission,
    despite the path segment's name. This mock's lookup is keyed on
    id_mission for exactly that reason -- mission.py itself is unmodified.

    No `?workflow=` override is accepted on this route (unlike the bare
    /index route, whose own ?workflow= override is unchanged 09A test
    infrastructure): the rendered workflow/identity is looked up
    deterministically from which synthetic mission id_value names. An
    unrecognized id returns 404 with NO identity or workflow DOM at all --
    never the old "both sections" graceful-default fallback."""
    try:
        id_mission = int(id_value)
    except ValueError:
        return HTMLResponse(content="<html><body>Not Found</body></html>", status_code=404)
    record = _SYNTHETIC_MISSIONS.get(id_mission)
    if record is None:
        return HTMLResponse(content="<html><body>Not Found</body></html>", status_code=404)
    return HTMLResponse(content=_render_mission_page(workflow=record["workflow"], identity=record))


@app.get("/SinAuto_MCMA/expertise/frontexpert")
def get_mission_search_page():
    """Logged-in mission-search markers (docs/recovery/PORTAL_CONTRACT.md §2/§3)."""
    html = (
        "<html><body>"
        "<form id='formRecherche'>"
        "<input id='ReferenceCie'><input id='Matricule'>"
        "</form>"
        "<a href='/SinAuto_MCMA/logout'>logout</a>"
        "<table id='listeSinistre'><tbody><tr><td>MEX202648130</td></tr></tbody></table>"
        "</body></html>"
    )
    return HTMLResponse(content=html)


@app.get("/SinAuto_MCMA/login")
def get_login_page():
    """Logged-out markers (docs/recovery/PORTAL_CONTRACT.md §2), or -- once
    the synthetic /front/Login/login call has succeeded -- the same
    logged-in markers used on the mission-search page, so an isolated-CI
    LoginCapability proof test can observe a real state transition on one
    fixed route without any credential automation."""
    if MOCK_STATE["logged_in"]:
        html = (
            "<html><body>"
            "<form id='formRecherche'>"
            "<input id='ReferenceCie'><input id='Matricule'>"
            "</form>"
            "<a href='/SinAuto_MCMA/logout'>logout</a>"
            "</body></html>"
        )
        return HTMLResponse(content=html)
    html = (
        "<html><body data-page-marker='expert_.phtml'>"
        "<form><input name='login' id='login'><input id='password' type='password'></form>"
        "</body></html>"
    )
    return HTMLResponse(content=html)


@app.post("/SinAuto_MCMA/front/Login/login")
def mock_login():
    MOCK_STATE["logged_in"] = True
    return JSONResponse({"state": "success", "message": "Login successful", "redirect": "/SinAuto_MCMA/expertise/frontexpert"})


_FIXED_MISSION = {
    "IdMission": 532805,
    "ReferenceMission": "3.MH.02.2026.00047",
    "RefSinistre": "MEX202648130",
    "Matricule": "34602-B-7",
    "Societaire": "SAPRESS SA",
    "ModeReparation": "GARAGE CONVENTIONNE",
}

# INC-09B amendment #2: a second synthetic mission whose own workflow is
# Mode Normal, distinct id/plate/id_sinistre from the PEC mission above.
# _FIXED_MISSION's id_mission (532805) is UNCHANGED, since 09A's own
# accepted test asserts `candidate.id_mission == 532805` -- only a new
# mission is ADDED, nothing existing is renumbered.
_SYNTHETIC_NORMAL_MISSION = {
    "IdMission": 612001,
    "ReferenceMission": "3.MH.02.2026.00099",
    "RefSinistre": "MEX202699001",
    "Matricule": "77001-C-3",
    "Societaire": "ATLAS ASSURANCE",
    "ModeReparation": "MODE NORMAL",
}

# Keyed by IdMission (int) -- see get_mission_deep_link's docstring for why
# the deep-link lookup must key on id_mission, not id_sinistre, given the
# accepted (unmodified) mission.py's own substitution behavior.
_SYNTHETIC_MISSIONS = {
    _FIXED_MISSION["IdMission"]: {
        "id_mission": _FIXED_MISSION["IdMission"],
        "id_sinistre": "534660",
        "matricule": _FIXED_MISSION["Matricule"],
        "ref_sinistre": _FIXED_MISSION["RefSinistre"],
        "workflow": "conventionne",
    },
    _SYNTHETIC_NORMAL_MISSION["IdMission"]: {
        "id_mission": _SYNTHETIC_NORMAL_MISSION["IdMission"],
        "id_sinistre": "699001",
        "matricule": _SYNTHETIC_NORMAL_MISSION["Matricule"],
        "ref_sinistre": _SYNTHETIC_NORMAL_MISSION["RefSinistre"],
        "workflow": "normal",
    },
}

_ALL_FIXED_MISSIONS = (_FIXED_MISSION, _SYNTHETIC_NORMAL_MISSION)


@app.post("/SinAuto_MCMA/expertise/FrontExpert/listeMissions")
async def mock_liste_missions(request: Request):
    """INC-09A: filters by Matricule so a non-matching search genuinely
    yields zero rows (needed for the exactly-one-search fail-closed proof;
    docs/recovery/KNOWN_FAILURES.md F3-F5). A blank/omitted Matricule
    returns EVERY fixed mission (unchanged 09A semantics, now extended to
    both synthetic missions -- no accepted test ever supplied a blank
    Matricule expecting exactly one row back). A matching Matricule
    returns exactly that one mission."""
    form = await _read_form(request)
    matricule = (form.get("Matricule") or "").strip()
    if not matricule:
        return JSONResponse({"data": list(_ALL_FIXED_MISSIONS)})
    matches = [m for m in _ALL_FIXED_MISSIONS if m["Matricule"] == matricule]
    return JSONResponse({"data": matches})


@app.post("/SinAuto_MCMA/expertise/notification/getAlerte/CodeAlerte/{code}")
async def mock_get_alerte(code: str, request: Request):
    form = await _read_form(request)
    length = form.get("length") or form.get("iDisplayLength") or "-1"
    rows = [
        {"idSinistre": 900001, "code": code, "libelle": f"Synthetic alert for {code} #1"},
        {"idSinistre": 900002, "code": code, "libelle": f"Synthetic alert for {code} #2"},
    ]
    if length not in ("-1", -1):
        try:
            rows = rows[: int(length)]
        except ValueError:
            pass
    return JSONResponse({"data": rows, "iTotalRecords": len(rows), "iTotalDisplayRecords": len(rows)})


# ---------------------------------------------------------------------------
# Route handlers -- Mode Normal row lifecycle
# ---------------------------------------------------------------------------


@app.post("/SinAuto_MCMA/expertise/gestionExpert/createRapportDefDet")
async def mock_create_rapport_det(request: Request):
    form = await _read_form(request)
    guard = _reject_if_charge_fields_present(form, "MODE_NORMAL")
    if guard is not None:
        return guard

    temp_row_id = form.get("TempRowId")
    if not temp_row_id:
        return JSONResponse({"state": "error", "reason": "MISSING_TEMP_ROW_ID"})

    if temp_row_id in MOCK_STATE["submitted_normal_temp_ids"]:
        MOCK_STATE["observability"]["duplicate_checkmark_attempts"]["MODE_NORMAL"] += 1
        return JSONResponse({"state": "error", "reason": "DUPLICATE_ROW_SUBMISSION"})

    MOCK_STATE["submitted_normal_temp_ids"].append(temp_row_id)
    row_id = MOCK_STATE["next_normal_row_id"]
    MOCK_STATE["next_normal_row_id"] += 1
    row = {
        "IdRapportDefDet": row_id,
        "IdRubrique": form.get("IdRubrique", ""),
        "MontantHT": form.get("MontantHT", "0.00"),
        "Taxe": form.get("Taxe", "0.00"),
        "MontantTTC": form.get("MontantTTC", "0.00"),
        "TauxVetuste": form.get("TauxVetuste", "0.00"),
        "MontantVetuste": form.get("MontantVetuste", "0.00"),
    }
    MOCK_STATE["rows"]["normal"].append(row)
    MOCK_STATE["observability"]["row_endpoint_calls"]["MODE_NORMAL"]["createRapportDefDet"] += 1
    MOCK_STATE["observability"]["redraw_version"]["MODE_NORMAL"] += 1
    return JSONResponse({"state": "success", "msg": "Rubrique enregistree.", "data": row})


@app.post("/SinAuto_MCMA/expertise/gestionExpert/listeRapportDefDet")
def mock_liste_rapport_det():
    return JSONResponse({"state": "success", "data": MOCK_STATE["rows"]["normal"]})


# ---------------------------------------------------------------------------
# Route handlers -- Garage Conventionne / PEC row lifecycle
# ---------------------------------------------------------------------------


@app.post("/SinAuto_MCMA/expertise/gestionexpert/updateDevisDet")
async def mock_update_devis_det(request: Request):
    form = await _read_form(request)
    guard = _reject_if_charge_fields_present(form, "GARAGE_CONVENTIONNE")
    if guard is not None:
        return guard

    nonce = form.get("SubmissionNonce")
    if not nonce:
        return JSONResponse({"state": "error", "reason": "MISSING_SUBMISSION_NONCE"})
    if nonce in MOCK_STATE["submitted_pec_nonces"]:
        MOCK_STATE["observability"]["duplicate_checkmark_attempts"]["GARAGE_CONVENTIONNE"] += 1
        return JSONResponse({"state": "error", "reason": "DUPLICATE_ROW_SUBMISSION"})

    try:
        id_devis_det = int(form.get("IdDevisDet", ""))
    except (TypeError, ValueError):
        return JSONResponse({"state": "error", "reason": "ROW_NOT_FOUND"})

    matches = [r for r in MOCK_STATE["rows"]["pec_validated"] if r["IdDevisDet"] == id_devis_det]
    if len(matches) != 1:
        return JSONResponse({"state": "error", "reason": "ROW_NOT_FOUND"})

    MOCK_STATE["submitted_pec_nonces"].append(nonce)
    row = matches[0]
    row["MontantHT"] = form.get("MontantHTValide", row["MontantHT"])
    row["Taxe"] = form.get("TaxeValide", row["Taxe"])
    row["MontantTTC"] = form.get("MontantTTCValide", row["MontantTTC"])
    row["TauxVetuste"] = form.get("TauxVetusteValide", row["TauxVetuste"])
    row["MontantVetuste"] = form.get("MontantVetusteValide", row["MontantVetuste"])

    MOCK_STATE["observability"]["row_endpoint_calls"]["GARAGE_CONVENTIONNE"]["updateDevisDet"] += 1
    MOCK_STATE["observability"]["redraw_version"]["GARAGE_CONVENTIONNE"] += 1
    return JSONResponse({"state": "success", "msg": "Detail devis mis a jour.", "data": row})


@app.post("/SinAuto_MCMA/expertise/gestiongarage/listeDevisDet")
def mock_liste_devis_det():
    return JSONResponse({"state": "success", "data": MOCK_STATE["rows"]["pec_validated"]})


# ---------------------------------------------------------------------------
# /_mock/* -- test-harness-only routes. Never a real portal path; grant no
# writer capability; never eligible for any live allowlist.
# ---------------------------------------------------------------------------


@app.get("/_mock/state")
def mock_get_state():
    return JSONResponse(MOCK_STATE)


@app.post("/_mock/reset")
def mock_reset():
    global MOCK_STATE
    MOCK_STATE = _initial_state()
    return JSONResponse({"state": "success"})


@app.post("/_mock/field_event")
async def mock_field_event(request: Request):
    body = await request.json()
    workflow = body.get("workflow")
    if workflow not in ("MODE_NORMAL", "GARAGE_CONVENTIONNE"):
        return JSONResponse({"state": "error", "reason": "UNKNOWN_WORKFLOW"})
    MOCK_STATE["observability"]["field_event_history"][workflow].append(
        {
            "row_id": body.get("row_id"),
            "field": body.get("field"),
            "event_type": body.get("event_type"),
        }
    )
    return JSONResponse({"state": "success"})


@app.get("/_mock/pec/original_rows")
def mock_pec_original_rows():
    return JSONResponse({"state": "success", "data": MOCK_STATE["rows"]["pec_original"]})


@app.post("/_mock/pec/preflight_match")
async def mock_pec_preflight_match(request: Request):
    """Mock-harness-only convenience: deterministic data-shape for exercising
    the 'exactly one match' preflight concept against fixed mock data. This
    is not the real preflight-matching algorithm -- that belongs to
    mcma.portal/execution (INC-09) and is out of scope for INC-06."""
    body = await request.json()
    planned_ids = body.get("planned_rubrique_ids", [])
    MOCK_STATE["observability"]["preflight_calls"]["GARAGE_CONVENTIONNE"].append(planned_ids)
    results = []
    all_matched = True
    for rubrique_id in planned_ids:
        matches = [r for r in MOCK_STATE["rows"]["pec_validated"] if r["IdRubrique"] == rubrique_id]
        match_count = len(matches)
        entry = {"rubrique_id": rubrique_id, "match_count": match_count}
        if match_count == 1:
            entry["matched_id_devis_det"] = matches[0]["IdDevisDet"]
        else:
            all_matched = False
        results.append(entry)
    return JSONResponse({"state": "success" if all_matched else "error", "all_matched": all_matched, "results": results})


@app.post("/_mock/normal/native_calculation")
async def mock_normal_native_calculation(request: Request):
    payload = await request.json()
    return JSONResponse(_simulate_native_calc("MODE_NORMAL", payload))


@app.get("/_mock/normal/financial_summary")
def mock_normal_financial_summary():
    return JSONResponse({"summary": MOCK_STATE["financial_summary"]["MODE_NORMAL"]})


@app.post("/_mock/pec/native_calculation")
async def mock_pec_native_calculation(request: Request):
    payload = await request.json()
    return JSONResponse(_simulate_native_calc("GARAGE_CONVENTIONNE", payload))


@app.get("/_mock/pec/financial_summary")
def mock_pec_financial_summary():
    return JSONResponse({"summary": MOCK_STATE["financial_summary"]["GARAGE_CONVENTIONNE"]})


if __name__ == "__main__":
    print("==================================================================")
    print("[*] Starting MCMA Local Mock Simulation Server on http://127.0.0.1:8080")
    print("    Fully offline -- no external CDN, font, or stylesheet reference.")
    print("    -> http://127.0.0.1:8080/SinAuto_MCMA/expertise/gestionexpert/index")
    print("==================================================================")
    uvicorn.run(app, host="127.0.0.1", port=8080, log_level="info")
