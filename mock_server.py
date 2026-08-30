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


def _simulate_native_calc(workflow: str, payload: dict) -> dict:
    guard = _reject_if_charge_fields_present(payload, workflow)
    if guard is not None:
        return {"state": "error", "reason": "DIRECT_CHARGE_FIELD_WRITE_REJECTED", "fields": sorted(ALL_CHARGE_FIELDS.intersection(payload.keys()))}

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

    obs["calculation_version"][workflow] += 1
    version = obs["calculation_version"][workflow]

    if simulate == "stale":
        previous = MOCK_STATE["financial_summary"][workflow]
        if previous is None:
            previous = {
                "charge_mutuelle": 0.0,
                "charge_societaire": 0.0,
                "calculation_version": version - 1,
            }
        stale_summary = dict(previous)
        stale_summary["stale"] = True
        MOCK_STATE["financial_summary"][workflow] = stale_summary
        MOCK_STATE["mismatch_injected"][workflow] = False
        return {"state": "success", "stale": True, "summary": stale_summary}

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
        return {"state": "success", "summary": computed}

    # success
    MOCK_STATE["financial_summary"][workflow] = computed
    MOCK_STATE["mismatch_injected"][workflow] = False
    return {"state": "success", "summary": computed}


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
        <span id="hdrRefSinistre"><b>Ref Sinistre:</b> MEX202648130</span>
        &nbsp;|&nbsp;
        <span id="hdrMatricule"><b>Matricule:</b> 34602-B-7</span>
        &nbsp;|&nbsp;
        <span class="badge-statut">DECLARE</span>
    </div>

    <form id="formExpertMission" onsubmit="return false;">
        <input type="hidden" id="IdSinistre__I" value="534660">
        <input type="hidden" id="IdMission" value="532805">

        <fieldset>
            <legend>Options</legend>
            <label><input type="checkbox" id="VehRepareI" checked> Vehicule Repare</label>
            <label><input type="checkbox" id="TvaRecupI" checked> TVA Recuperable</label>
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
                    <label>Devis TTC:</label> <input type="text" id="DevisMontantTTC" value="11200.00" readonly>
                    <label>Devis TVA:</label> <input type="text" id="DevisMontantTVA" value="1866.67" readonly>
                    <label>Vetuste Total:</label> <input type="text" id="DevisMontantVetusteTotal" value="0.00">
                    <label>Franchise:</label> <input type="text" id="DevisMontantFranchise" value="0.00">
                    <label>Remise:</label> <input type="text" id="DevisMontantRemise" value="0.00">
                    <br><br>
                    <label>Charge Societaire:</label>
                    <input type="text" id="DevisMontantChargeSocietaire" value="0.00" disabled>
                    <label>Charge Mutuelle:</label>
                    <input type="text" id="DevisMontantChargeMutuelle" value="0.00" disabled>
                    <div class="mock-only-note">DevisCalculerMontantCharge() is the confirmed PEC client-side function; its HTTP mirror (/_mock/pec/native_calculation) is mock-only test infrastructure, not a confirmed live network endpoint.</div>
                    <select id="mockSimulatePec"><option value="success">success</option><option value="stale">stale</option><option value="missing">missing</option><option value="failed">failed</option><option value="mismatch">mismatch</option></select>
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
                    <label>Mt Reparation:</label> <input type="text" id="MontantReparation" value="0.00">
                    <label>Franchise:</label> <input type="text" id="MontantFranchise" value="0.00">
                    <label>Vetuste Total:</label> <input type="text" id="MontantVetusteTotal" value="0.00">
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

    // ---------------- Mode Normal ----------------
    var normalTempCounter = 0;

    function ajouterLigneModeNormal() {
        normalTempCounter++;
        var tempId = "tmp-" + normalTempCounter;
        var tr = document.createElement("tr");
        tr.id = "normal_row_" + tempId;
        tr.className = "tr-editing";

        var rubTd = document.createElement("td");
        var sel = document.createElement("select");
        [["1","FOURNITURES CARROSSERIE (ORIGINES)"],["3","FOURNITURES CARROSSERIE (RECUPERABLES)"],["7","MAIN D'OEUVRE CARROSSERIE"],["12","MAIN D'OEUVRE PEINTURE"],["16","PEINTURES ET INGREDIENTS"]].forEach(function(o) {
            var opt = document.createElement("option"); opt.value = o[0]; opt.textContent = o[1]; sel.appendChild(opt);
        });
        sel.id = "IdRubrique_" + tempId;
        wireFieldEvents(sel, "MODE_NORMAL", tempId, "IdRubrique");
        rubTd.appendChild(sel); tr.appendChild(rubTd);

        ["MontantHT", "Taxe", "TauxVetuste", "MontantVetuste"].forEach(function(field) {
            var td = document.createElement("td");
            var input = document.createElement("input");
            input.type = "text"; input.id = field + "_" + tempId; input.value = field === "MontantHT" || field === "Taxe" ? "" : "0.00";
            wireFieldEvents(input, "MODE_NORMAL", tempId, field);
            td.appendChild(input); tr.appendChild(td);
        });

        var ttcTd = document.createElement("td");
        var ttcInput = document.createElement("input");
        ttcInput.type = "text"; ttcInput.id = "MontantTTC_" + tempId; ttcInput.readOnly = true; ttcInput.value = "0.00";
        ttcTd.appendChild(ttcInput); tr.appendChild(ttcTd);

        var actionTd = document.createElement("td");
        var check = document.createElement("a");
        check.className = "btn-check"; check.textContent = "OK"; check.onclick = function() { saveNormalRow(tempId); };
        actionTd.appendChild(check); tr.appendChild(actionTd);

        document.getElementById("tbodyModeNormal").prepend(tr);
        logHUD("Mode Normal: Ajouter + created exactly one temporary row (" + tempId + ").");
    }

    function saveNormalRow(tempId) {
        var rubSel = document.getElementById("IdRubrique_" + tempId);
        var fields = {
            IdRubrique: rubSel.value,
            MontantHT: document.getElementById("MontantHT_" + tempId).value || "0.00",
            Taxe: document.getElementById("Taxe_" + tempId).value || "0.00",
            MontantTTC: document.getElementById("MontantTTC_" + tempId).value || "0.00",
            TauxVetuste: document.getElementById("TauxVetuste_" + tempId).value || "0.00",
            MontantVetuste: document.getElementById("MontantVetuste_" + tempId).value || "0.00",
            TempRowId: tempId
        };
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
            tr.id = "row_val_" + item.IdDevisDet;
            var labelTd = document.createElement("td"); labelTd.textContent = item.LibRubrique; tr.appendChild(labelTd);
            ["MontantHT", "Taxe", "MontantTTC", "TauxVetuste", "MontantVetuste"].forEach(function(f) {
                var td = document.createElement("td"); td.className = "text-right col-" + f; td.textContent = item[f]; tr.appendChild(td);
            });
            var actionTd = document.createElement("td");
            var pencil = document.createElement("a");
            pencil.className = "btn-pencil"; pencil.textContent = "edit"; pencil.onclick = (function(id) { return function() { editRowTable2(id); }; })(item.IdDevisDet);
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
        var tr = document.getElementById("row_val_" + id);
        tr.classList.add("tr-editing");
        ["MontantHT", "Taxe", "TauxVetuste", "MontantVetuste"].forEach(function(f) {
            var td = tr.querySelector(".col-" + f);
            var current = td.textContent;
            td.innerHTML = "";
            var input = document.createElement("input");
            input.type = "text"; input.id = f + "Valide_" + id; input.value = current;
            wireFieldEvents(input, "GARAGE_CONVENTIONNE", String(id), f);
            td.appendChild(input);
        });
        var actionTd = tr.querySelector("td:last-child");
        actionTd.innerHTML = "";
        var check = document.createElement("a");
        check.className = "btn-check"; check.textContent = "OK"; check.onclick = function() { saveRowTable2(id); };
        actionTd.appendChild(check);
        logHUD("PEC: row " + id + " entered edit mode (exact row only).");
    }

    function saveRowTable2(id) {
        pecNonceCounter++;
        var fields = {
            IdDevisDet: id,
            MontantHTValide: document.getElementById("MontantHTValide_" + id).value,
            TaxeValide: document.getElementById("TaxeValide_" + id).value,
            MontantTTCValide: document.getElementById("MontantTTCValide_" + id) ? document.getElementById("MontantTTCValide_" + id).value : "0.00",
            TauxVetusteValide: document.getElementById("TauxVetusteValide_" + id).value,
            MontantVetusteValide: document.getElementById("MontantVetusteValide_" + id).value,
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
            franchise: document.getElementById("DevisMontantFranchise").value || "0",
            vetuste: document.getElementById("DevisMontantVetusteTotal").value || "0",
            remise: document.getElementById("DevisMontantRemise").value || "0",
            part_resp: "100",
            simulate: document.getElementById("mockSimulatePec").value
        };
        postJson("/_mock/pec/native_calculation", payload).then(function(res) {
            if (res.state === "success" && res.summary) {
                document.getElementById("DevisMontantChargeMutuelle").value = res.summary.charge_mutuelle;
                document.getElementById("DevisMontantChargeSocietaire").value = res.summary.charge_societaire;
                logHUD("DevisCalculerMontantCharge() (" + payload.simulate + ") executed.");
            } else {
                logHUD("DevisCalculerMontantCharge() FAILED: " + res.reason);
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


def _render_mission_page() -> str:
    return HTML_TEMPLATE.replace("__PEC_ORIGINAL_ROWS__", _render_pec_original_rows())


# ---------------------------------------------------------------------------
# Route handlers -- mission page, auth/session, notifications
# ---------------------------------------------------------------------------


@app.get("/")
@app.get("/SinAuto_MCMA/expertise/gestionexpert/index")
@app.get("/SinAuto_MCMA/expertise/gestionExpert/index")
def get_mission_page():
    return HTMLResponse(content=_render_mission_page())


@app.get("/SinAuto_MCMA/expertise/gestionExpert/getSinistre/idSinistre/{id_sinistre}/rubrique/gestionexpert-index")
def get_mission_deep_link(id_sinistre: str):
    return HTMLResponse(content=_render_mission_page())


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


@app.post("/SinAuto_MCMA/expertise/FrontExpert/listeMissions")
def mock_liste_missions():
    return JSONResponse(
        {
            "data": [
                {
                    "IdMission": 532805,
                    "ReferenceMission": "3.MH.02.2026.00047",
                    "RefSinistre": "MEX202648130",
                    "Matricule": "34602-B-7",
                    "Societaire": "SAPRESS SA",
                    "ModeReparation": "GARAGE CONVENTIONNE",
                }
            ]
        }
    )


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
